# 部署手册

部署到腾讯云 SCF，**两个函数共用一个依赖 Layer**（挂载到 `/opt/python`，函数代码包只含 `app/`）：

- **Event 函数 `pusher-pipeline` + 每日 08:00 Timer** —— 定时日报流水线。
- **Web 函数 `pusher-go-advanced`（uvicorn）+ 函数 URL** —— CLI 的 HTTP API。

> **为什么是这套？** 该账号 **API 网关已停售**（2024-07-01 起不能新建触发器，2025-06-30
> 触发器下线），SCF 的 HTTP/Web 函数也只能挂 `apigw` 触发器（**不能挂 timer**），且
> serverless-tencent 组件在本环境不可用（v4 需登录、v3 在 CN 被地域限制）。所以：
> - HTTP API 用 **函数 URL** 暴露——这是 API 网关停售后的官方替代，给函数一个**永久公网
>   HTTPS 端点**（`https://<app-id>-<url-id>.<region>.tencentscf.com`），不依赖网关。
> - 定时日报用单独的 **Event 函数 + Timer**（timer 只能挂事件函数）。
>
> **函数 URL 需在控制台为该 Web 函数手动启用一次**（授权类型选「开放」，鉴权交给后端的
> bearer token）。SDK 3.1.100 既不能开启、也读不到它，故启用后把永久地址写入
> `deploy/.env` 的 `API_FUNCTION_URL`，`deploy.sh` 会据此打印 CLI 接入命令。

## 一键部署

前置：建好数据库（见下方[数据库](#数据库)）、装好 Docker 与 `server/.venv`，然后：

```bash
source deploy/.env          # 内含 MYSQL_* / TENCENT_* / DEEPSEEK_* / KIMI_* / EMAIL_* / TIMER_SECRET
bash deploy/deploy.sh
```

`deploy.sh` 全自动完成：

1. 在 `python:3.10-slim` **(linux/amd64)** 内装依赖并精简（strip `.so`、去 pytest、删 tests，
   并把 efinance 缓存目录改到 `/tmp`）→ 打成 `layer.zip`；
2. 用 `publish_layer.py` 上传 COS 并发布 **Layer 版本**；
3. 用 `deploy_scf.py` 创建/更新 **Event 函数 `pusher-pipeline`** 并幂等挂上**每日 Timer**
   （`TIMER_SECRET` 同时注入函数环境变量与触发器 `CustomArgument`，自动保持一致）；
4. 再用 `deploy_scf.py` 创建/更新 **Web 函数 `pusher-go-advanced`**（HTTP 类型，handler
   `scf_bootstrap`），并打印其**函数 URL** 与 CLI 接入命令（地址取自 `API_FUNCTION_URL`）。

脚本可重复执行（幂等）：函数已存在则只更新代码与配置，Timer 先删后建。

> 首次启用函数 URL：第一次部署后，到控制台为 `pusher-go-advanced` 开启「函数 URL」
> （授权类型「开放」），把永久地址写进 `deploy/.env` 的 `API_FUNCTION_URL`，再跑一次脚本，
> 末尾就会打印 `pusher` 的接入命令。之后 CLI 直接 `pusher register/portfolio/trigger/report`。

## 关键约束（脚本已处理）

- **必须 amd64**：SCF 运行时是 x86_64，Apple Silicon 默认的 arm64 包会让 numpy 等崩溃，
  故依赖在 `docker run --platform linux/amd64` 内构建。
- **依赖走 Layer**：全打进函数代码包会超 SCF 体积限制（报「参数与规范不符」）。
- **`/opt/python` 上 sys.path**：Event 函数不跑 `scf_bootstrap`，且 SCF 禁止设置
  `PYTHONPATH` 环境变量（`EnvironmentSystemProtect`），故 `scf_event_handler.py` 自行把
  `/opt/python` 插入 `sys.path`。
- **只有 `/tmp` 可写**：handler 里设 `HOME=/tmp`，efinance 缓存目录也改到 `/tmp`。
- **境内 LLM 较慢**：`LLM_TIMEOUT` 默认 300s，整轮约 5-6 分钟（yfinance 拉美股最慢）。

## 数据库

`MYSQL_HOST` 用 TDSQL-C **外网地址**即可（函数默认有公网出口）。建表：本地能连库时
`mysql -h <host> -u <user> -p pusher < sql/schema.sql`；连不到时用腾讯云 **DMC 控制台**
的 SQL 窗口执行 `sql/schema.sql`。

## 环境变量（`deploy/.env`）

`deploy/.env` 已被 `.gitignore` 忽略，**切勿提交机密**。需包含：

```bash
# 数据库
MYSQL_HOST=...  MYSQL_PORT=...  MYSQL_USER=root  MYSQL_PASSWORD=...  MYSQL_DATABASE=pusher
# 腾讯云凭证（部署用）
TENCENT_SECRET_ID=...  TENCENT_SECRET_KEY=...
# LLM：DeepSeek + Kimi(Moonshot) 双供应商，按模型名前缀自动路由（kimi-* → Moonshot）
DEEPSEEK_API_KEY=...  KIMI_API_KEY=...  KIMI_ENDPOINT=https://api.moonshot.cn/v1
PLANNER_MODEL=deepseek-v4-pro       # 规划
ANALYST_MODEL=deepseek-v4-flash     # 市场/新闻/板块/顾问
REVIEWER_MODEL=kimi-k2.6            # 主编终审
# 邮件 + 定时密钥
EMAIL_SMTP_HOST=smtp.qq.com  EMAIL_SMTP_PORT=587  EMAIL_FROM=...  EMAIL_PASSWORD=...
TIMER_SECRET=$(openssl rand -hex 16)
# CLI HTTP API 的函数 URL（控制台手动启用后填，地址永久不变；SDK 读不到，此处记一次）
API_FUNCTION_URL=https://<app-id>-<url-id>.ap-shanghai.tencentscf.com
```

> 模型名必须与供应商实际型号一致（可用 `GET /v1/models` 查 Moonshot 型号；Moonshot 的
> 2.7 仅有 code 版，通用写作建议 `kimi-k2.6`）。

## 手动触发与验证

手动异步触发一次（部署脚本结束时也会打印同样的片段）：

```bash
source deploy/.env
python - <<'PY'
import os, json
from tencentcloud.common import credential
from tencentcloud.scf.v20180416 import scf_client, models
cli = scf_client.ScfClient(credential.Credential(
    os.environ["TENCENT_SECRET_ID"], os.environ["TENCENT_SECRET_KEY"]), "ap-shanghai")
ir = models.InvokeRequest(); ir.FunctionName = "pusher-pipeline"; ir.InvocationType = "Event"
ir.ClientContext = json.dumps({"Type": "Timer", "Message": os.environ["TIMER_SECRET"]})
print(cli.Invoke(ir).Result.FunctionRequestId)
PY
```

约 5-6 分钟后，查 `jobs` 表对应 job 为 `done`、`reports` 表有当日记录、并收到日报邮件。

---

> `serverless.yml` / `build_layer.sh` 为旧的 serverless 组件方案，在本账号不可用，仅作历史参考。
