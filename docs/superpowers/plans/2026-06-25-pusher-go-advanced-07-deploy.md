# Pusher-Go Advanced — 子计划 7: SCF 部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Python 后端打包部署为腾讯云 SCF Web 函数，绑定 API 网关与每日定时触发器，依赖通过 COS/Layer 分层，并给出 Rust CLI 的跨平台发布构建。

**Architecture:** 后端以 Web 函数形态运行（`scf_bootstrap` 拉起 uvicorn 监听 9000 端口）。重型 Python 依赖打成 Layer 经 COS 上传，函数代码包仅含 `app/`。API 网关提供 HTTPS 入口；Timer 触发器每日 8:00（北京）以 `POST /` 投递事件，根处理器校验密钥后入队全量流水线 job。

**Tech Stack:** 腾讯云 SCF（Python 3.10 Web 函数）、API 网关、Timer 触发器、COS、Serverless Framework（`serverless.yml`）或 SCF 控制台；Rust 交叉编译。

## Global Constraints

- 继承子计划 1–6 的全部产物。
- 函数内存 **512MB–1024MB**，超时 **300–600s**（异步 job 在后台执行，但首个请求需立即返回）。
- 机密（DB 密码、API Key、SMTP 密码、`TIMER_SECRET`）只经 SCF 环境变量注入，**绝不进仓库**。
- Web 函数监听 **0.0.0.0:9000**（SCF Web 函数约定端口）。
- ⚠️ **部署前以腾讯云最新文档核对两点**：①Web 函数 Timer 事件的投递路径与 body 结构；②Web 函数依赖分层/包体积上限。下文按"Timer 以 `POST /`、body 含 `Type=Timer` 与自定义 `Message`"实现，若实际契约不同需相应调整 Task 2。

---

## File Structure

- `server/app/api/health.py` — `/health` 健康检查。
- `server/scf_bootstrap` — Web 函数启动脚本（可执行）。
- `server/app/api/timer.py` — **修改**：新增 SCF 根路径 Timer 分发。
- `server/app/main.py` — **修改**：挂载 health 路由。
- `deploy/serverless.yml` — SCF 部署描述。
- `deploy/build_layer.sh` — 依赖分层打包脚本。
- `deploy/README.md` — 部署运行手册。
- `cli/build-release.sh` — CLI 跨平台构建脚本。

---

## Task 1: 健康检查 + 启动脚本

**Files:**
- Create: `server/app/api/health.py`, `server/scf_bootstrap`
- Modify: `server/app/main.py`
- Test: `server/tests/test_health.py`

**Interfaces:**
- Produces:
  - `GET /health` → `{"status": "ok"}`（无需鉴权，供 API 网关/烟测探活）。
  - `server/scf_bootstrap` — 启动 uvicorn 监听 9000。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_health.py`:

```python
from fastapi.testclient import TestClient
from app.main import app


def test_health_ok():
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_health.py -v`
Expected: FAIL（404）。

- [ ] **Step 3: 写 health 路由并挂载**

Create `server/app/api/health.py`:

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}
```

Edit `server/app/main.py`，加入 health 路由（置于其他路由之前）：

```python
from fastapi import FastAPI
from app.api import auth, portfolio, report, job, timer, health

app = FastAPI(title="pusher-go-advanced")
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(portfolio.router)
app.include_router(report.router)
app.include_router(job.router)
app.include_router(timer.router)
```

- [ ] **Step 4: 写 scf_bootstrap**

Create `server/scf_bootstrap`:

```bash
#!/bin/bash
# SCF Web 函数入口：监听 9000。依赖（含 Layer）通常挂载在 /opt，
# 部署时把 PYTHONPATH 指向 Layer 解压目录。
export PYTHONPATH="/var/user:/opt:${PYTHONPATH}"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 9000
```

设为可执行：

```bash
chmod +x server/scf_bootstrap
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_health.py -v`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/api/health.py server/scf_bootstrap server/app/main.py server/tests/test_health.py
git commit -m "feat(deploy): add health endpoint and scf web bootstrap"
```

---

## Task 2: SCF Timer 根路径分发

**Files:**
- Modify: `server/app/api/timer.py`
- Test: `server/tests/test_timer_root.py`

**Interfaces:**
- Produces:
  - `POST /`（根路径）：解析 SCF Timer 事件 body；当 `body.Type == "Timer"` 且 `body.Message == TIMER_SECRET` 时，入队全量 pipeline job 并 202 返回 `{job_id}`；否则 401。复用 `run_job` 后台执行。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_timer_root.py`:

```python
import pytest
from fastapi.testclient import TestClient
from app.db import mysql
from app.main import app
from app.models import job
import app.api.timer as timer_api


@pytest.fixture(autouse=True)
def _reset(db_conn, monkeypatch):
    mysql.reset_connection()
    monkeypatch.setattr(timer_api, "run_job", lambda jid: job.mark_done(jid, "2026-06-25"))
    monkeypatch.setenv("TIMER_SECRET", "s3cr3t")
    yield
    mysql.reset_connection()


@pytest.fixture
def client():
    return TestClient(app)


def test_root_timer_enqueues_with_valid_secret(client):
    r = client.post("/", json={"Type": "Timer", "Message": "s3cr3t"})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    assert job.get_job(jid)["status"] == "done"


def test_root_timer_rejects_bad_secret(client):
    r = client.post("/", json={"Type": "Timer", "Message": "wrong"})
    assert r.status_code == 401


def test_root_non_timer_rejected(client):
    r = client.post("/", json={"foo": "bar"})
    assert r.status_code == 401
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_timer_root.py -v`
Expected: FAIL（404/405，根路由未定义）。

- [ ] **Step 3: 写实现（追加到 timer.py）**

在 `server/app/api/timer.py` 追加（保留已有 `/internal/timer`）：

```python
from fastapi import Request


@router.post("/")
async def scf_timer_root(request: Request, background: BackgroundTasks):
    try:
        body = await request.json()
    except Exception:
        body = {}
    expected = os.environ.get("TIMER_SECRET")
    if body.get("Type") != "Timer" or not expected or body.get("Message") != expected:
        raise HTTPException(status_code=401, detail="invalid timer event")
    job_id = job_model.create_job("pipeline", user_id=None)
    background.add_task(run_job, job_id)
    return {"job_id": job_id}
```

> 注：根处理器与 API 网关的常规请求互不影响——网关业务路径都带具体 path（`/login` 等），只有 Timer 投递到 `/`。Timer 的"用户附加信息(Message)"在控制台/`serverless.yml` 配置为 `TIMER_SECRET` 同值。

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_timer_root.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 跑全量后端测试**

Run: `cd server && python3 -m pytest -v`
Expected: 全绿。

- [ ] **Step 6: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/api/timer.py server/tests/test_timer_root.py
git commit -m "feat(deploy): handle scf timer event at root path"
```

---

## Task 3: 依赖分层打包脚本

**Files:**
- Create: `deploy/build_layer.sh`

**Interfaces:**
- Produces: `deploy/build_layer.sh` — 在 Linux 容器内安装依赖到 `layer/python/`，产出可上传为 SCF Layer 的 `layer.zip`（解压后挂载到 `/opt`）。

- [ ] **Step 1: 写脚本**

Create `deploy/build_layer.sh`:

```bash
#!/bin/bash
set -euo pipefail
# 在与 SCF 运行时一致的 Linux 环境构建依赖层（macOS 本机产物不可用于 SCF）。
# 用法: bash deploy/build_layer.sh

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/deploy/layer"
rm -rf "$OUT" && mkdir -p "$OUT/python"

docker run --rm -v "$ROOT":/work -w /work python:3.10-slim bash -c "
  pip install --no-cache-dir -r server/requirements.txt -t deploy/layer/python
"

cd "$OUT" && zip -r -q "$ROOT/deploy/layer.zip" python
echo "built: $ROOT/deploy/layer.zip"
```

设为可执行：

```bash
chmod +x deploy/build_layer.sh
```

- [ ] **Step 2: 校验脚本语法（不实际跑 docker）**

Run: `bash -n deploy/build_layer.sh && echo OK`
Expected: 输出 `OK`（语法检查通过）。

> 实际构建需本机有 Docker；产物 `deploy/layer.zip` 用于创建 SCF Layer。`layer.zip` 与 `deploy/layer/` 较大，应加入 `.gitignore`，不提交。

- [ ] **Step 3: 写 .gitignore（若不存在则创建，存在则追加）**

Create or append `.gitignore`（仓库根）:

```
# build artifacts
deploy/layer/
deploy/layer.zip
server/__pycache__/
**/__pycache__/
cli/target/
.env
```

- [ ] **Step 4: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add deploy/build_layer.sh .gitignore
git commit -m "build(deploy): add dependency layer build script"
```

---

## Task 4: SCF 部署描述 + 运行手册

**Files:**
- Create: `deploy/serverless.yml`, `deploy/README.md`

**Interfaces:**
- Produces: 可用 Serverless Framework 部署的 `serverless.yml`（Web 函数 + API 网关 + Timer + Layer 引用），以及人工运行手册。

- [ ] **Step 1: 写 serverless.yml**

Create `deploy/serverless.yml`:

```yaml
# 部署: 安装 serverless 后在 deploy/ 目录执行 `serverless deploy`
# 机密通过环境变量/CI Secret 注入，勿写死。
component: scf
name: pusher-go-advanced

inputs:
  name: pusher-go-advanced
  src:
    src: ../server
    exclude:
      - tests/**
      - __pycache__/**
  handler: scf_bootstrap        # Web 函数：可执行启动脚本
  runtime: Python3.10
  region: ap-guangzhou
  memorySize: 1024
  timeout: 600
  type: web                     # Web 函数
  layers:
    - name: pusher-deps         # 预先用 layer.zip 创建的 Layer 名
      version: 1
  environment:
    variables:
      MYSQL_HOST: ${env:MYSQL_HOST}
      MYSQL_PORT: ${env:MYSQL_PORT}
      MYSQL_USER: ${env:MYSQL_USER}
      MYSQL_PASSWORD: ${env:MYSQL_PASSWORD}
      MYSQL_DATABASE: ${env:MYSQL_DATABASE}
      DEEPSEEK_API_KEY: ${env:DEEPSEEK_API_KEY}
      DEEPSEEK_MODEL: ${env:DEEPSEEK_MODEL}
      PLANNER_MODEL: ${env:PLANNER_MODEL}
      EMAIL_SMTP_HOST: ${env:EMAIL_SMTP_HOST}
      EMAIL_SMTP_PORT: ${env:EMAIL_SMTP_PORT}
      EMAIL_FROM: ${env:EMAIL_FROM}
      EMAIL_PASSWORD: ${env:EMAIL_PASSWORD}
      TIMER_SECRET: ${env:TIMER_SECRET}
  events:
    - apigw:
        parameters:
          protocols:
            - https
          endpoints:
            - path: /
              method: ANY
    - timer:
        parameters:
          name: daily-pipeline
          # SCF 7 段 cron（秒 分 时 日 月 周 年），每天 08:00（默认 UTC+8）
          cronExpression: "0 0 8 * * * *"
          enable: true
          argument: "s3cr3t-REPLACE-WITH-TIMER_SECRET"   # 投递为 body.Message
```

> 关键点：`type: web` + `handler: scf_bootstrap`；API 网关 `path: /` `method: ANY` 把全部 HTTP 透传给 FastAPI；Timer 的 `argument` 必须与 `TIMER_SECRET` 一致（它会成为事件 body 的 `Message`）。

- [ ] **Step 2: 校验 YAML 可解析**

Run:
```bash
cd /Users/chris/Documents/pusher-go-advanced
python3 -c "import yaml,sys; yaml.safe_load(open('deploy/serverless.yml')); print('YAML OK')"
```
Expected: 输出 `YAML OK`。

- [ ] **Step 3: 写部署运行手册**

Create `deploy/README.md`:

```markdown
# 部署手册

## 0. 准备
- 腾讯云账号，开通 SCF / API 网关 / CDB(MySQL) / COS。
- 本机安装 Docker（构建依赖层）与 Serverless Framework：`npm i -g serverless`。
- 配置腾讯云凭证：`export TENCENT_SECRET_ID=... TENCENT_SECRET_KEY=...`。

## 1. 数据库
1. 创建 CDB MySQL（最小 1核1G），库名 `pusher`。
2. 应用建表脚本：
   ```bash
   mysql -h <host> -u <user> -p pusher < sql/schema.sql
   ```
3. 安全组只放行 SCF 出口网段访问 3306。
4. （可选）插入初始 RSS 源：
   ```sql
   INSERT INTO rss_sources (name, url, category) VALUES
     ('华尔街见闻', 'https://dedicated-feed-url', 'business');
   ```

## 2. 依赖层
```bash
bash deploy/build_layer.sh           # 产出 deploy/layer.zip
```
在 SCF 控制台 → 层管理 → 新建层，运行时 Python3.10，上传 `layer.zip`（>50MB 经 COS）。记下层名 `pusher-deps` 与版本号，回填 `serverless.yml` 的 `layers`。

## 3. 环境变量
导出全部机密（见 spec §7.2 + `TIMER_SECRET`）：
```bash
export MYSQL_HOST=... MYSQL_USER=... MYSQL_PASSWORD=... MYSQL_DATABASE=pusher
export MYSQL_PORT=3306
export DEEPSEEK_API_KEY=... DEEPSEEK_MODEL=deepseek-chat PLANNER_MODEL=deepseek-r1
export EMAIL_SMTP_HOST=smtp.gmail.com EMAIL_SMTP_PORT=587 EMAIL_FROM=... EMAIL_PASSWORD=...
export TIMER_SECRET=$(openssl rand -hex 16)
```
把 `serverless.yml` 里 timer 的 `argument` 改为与 `TIMER_SECRET` 相同的值。

## 4. 部署
```bash
cd deploy && serverless deploy
```
输出里记下 API 网关 HTTPS 地址。

## 5. 烟测
```bash
curl https://<apigw-host>/health        # 期望 {"status":"ok"}
```
用 CLI 走通注册→加持仓→触发：
```bash
export PUSHER_ENDPOINT=https://<apigw-host>
pusher register --email you@x.com
pusher portfolio add-stock 600519 --quantity 100
pusher trigger run                       # 触发并轮询至 done
pusher report today
```

## 6. 验证定时
等次日 8:00，或在控制台手动触发 timer，确认收到日报邮件、`reports` 表有当日记录、`jobs` 表对应 job 为 done。
```

- [ ] **Step 4: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add deploy/serverless.yml deploy/README.md
git commit -m "docs(deploy): add serverless config and deployment runbook"
```

---

## Task 5: CLI 跨平台发布构建

**Files:**
- Create: `cli/build-release.sh`

**Interfaces:**
- Produces: `cli/build-release.sh` — 为 4 个目标三元组构建 release 二进制（spec §6.3）。

- [ ] **Step 1: 写脚本**

Create `cli/build-release.sh`:

```bash
#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

TARGETS=(
  aarch64-apple-darwin
  x86_64-apple-darwin
  x86_64-unknown-linux-gnu
  x86_64-pc-windows-gnu
)

for t in "${TARGETS[@]}"; do
  echo "==> building $t"
  rustup target add "$t" || true
  cargo build --release --target "$t"
done

echo "done. binaries under cli/target/<target>/release/"
```

设为可执行：

```bash
chmod +x cli/build-release.sh
```

- [ ] **Step 2: 校验脚本语法 + 本机原生构建**

Run:
```bash
bash -n cli/build-release.sh && echo OK
cd cli && cargo build --release
```
Expected: `OK` + 本机 release 构建成功（产出 `cli/target/release/pusher`）。跨平台 target 需对应工具链（如 Windows 需 `mingw-w64`、Linux 交叉需 gnu 工具链），在 CI 或具备工具链的机器执行完整脚本。

- [ ] **Step 3: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add cli/build-release.sh
git commit -m "build(cli): add cross-platform release build script"
```

---

## Self-Review

**1. Spec coverage（范围 = spec v2 §7 部署 + §5.2 Timer + §6.3 跨平台）：**
- SCF Web 函数 + bootstrap + 内存/超时 → Task 1/4。✅
- API 网关 HTTPS 入口（ANY /）→ Task 4 serverless.yml。✅
- Timer 每日 8:00 + 7 段 cron + 密钥校验 → Task 2/4。✅
- 依赖 COS/Layer 分层 → Task 3 + README。✅
- 环境变量清单（§7.2 + TIMER_SECRET）→ Task 4 serverless.yml + README。✅
- CDB 建表 + 安全组白名单（§9）→ README。✅
- CLI 四目标交叉编译（§6.3）→ Task 5。✅

**2. Placeholder 扫描：** 无 TBD/占位；脚本、yaml、runbook 均为完整可用内容。`argument`/层版本号等需部署者按自身环境替换的占位已显式标注（非计划缺失）。✅

**3. 类型/契约一致性：** `/health`、根 Timer 处理器复用 `run_job`/`create_job`（与子计划 5 一致）；`TIMER_SECRET` 在 timer 路由、serverless.yml `argument`、README 三处语义一致；CLI `PUSHER_ENDPOINT` 与子计划 6 `resolve_endpoint` 一致。✅

**4. 部署期需人工核对的假设（已在 Global Constraints 标注）：** SCF Web 函数 Timer 的投递路径/body 结构、依赖分层上限——部署前以腾讯云最新文档确认，必要时调整 Task 2 的根处理器与 Task 3 的分层方式。
