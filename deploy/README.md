# 部署手册

## 一键部署（推荐）

> **架构说明**：该账号 **API 网关已停售**、HTTP/Web 函数**不能挂 timer**、
> serverless-tencent 组件在本环境不可用。因此**不走 serverless 组件**，改为直接用
> SCF SDK 部署。每日日报 = **Event 函数 `pusher-pipeline` + 每日 08:00 Timer**；
> 依赖打成 **Layer**（挂载到 `/opt/python`），函数代码包只含 `app/`。
> CLI 的 HTTP API 因 API 网关停售**暂未部署**，用户/持仓暂用 SQL 维护。

先建好数据库（见下方第 1 节）、装好 Docker 与 `server/.venv`，然后：

```bash
source deploy/.env          # 内含 MYSQL_* / TENCENT_* / DEEPSEEK_* / KIMI_* / EMAIL_* / TIMER_SECRET
bash deploy/deploy.sh
```

`deploy.sh` 全自动完成：
1. 在 `python:3.10-slim` **(linux/amd64)** 内装依赖并精简（strip .so、去 pytest、删 tests，
   并把 efinance 缓存目录改到 `/tmp`）→ 打成 `layer.zip`；
2. 用 `publish_layer.py` 上传 COS 并发布 **Layer 版本**；
3. 用 `deploy_scf.py` 创建/更新 **Event 函数** 并幂等挂上**每日 Timer**（`TIMER_SECRET`
   同时注入函数环境变量与触发器 `CustomArgument`，自动一致）。

关键约束（已在脚本里处理）：

- **必须 amd64**：SCF 运行时是 x86_64，Apple Silicon 默认的 arm64 包会让 numpy 等崩溃。
- **依赖走 Layer**：全打进函数代码包会超 SCF 体积限制。
- **`/opt/python` 上 sys.path**：Event 函数不跑 `scf_bootstrap`，且 SCF 禁止设置
  `PYTHONPATH` 环境变量，故 `scf_event_handler.py` 自行把 `/opt/python` 插入 `sys.path`。
- **只有 `/tmp` 可写**：handler 里设 `HOME=/tmp`。

> `serverless.yml` / `build_layer.sh` 及下方「分步手册」为旧的 serverless 组件方案，
> 在本账号不可用，仅作历史参考。

### 数据库

`MYSQL_HOST` 用 TDSQL-C **外网地址**即可（函数默认有公网出口）。本地连不到内网库时，
用腾讯云 **DMC 控制台** 的 SQL 窗口执行 `sql/schema.sql`，或临时开外网地址执行完再关。

---

## 0. 准备（分步手册）
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
# LLM：DeepSeek + Kimi(Moonshot) 双供应商，按模型名前缀自动路由
export DEEPSEEK_API_KEY=... KIMI_API_KEY=...
export KIMI_ENDPOINT=https://api.moonshot.cn/v1            # 国际站用 api.moonshot.ai/v1
# 各角色模型（kimi-* 走 Moonshot，其余走 DeepSeek）
export PLANNER_MODEL=deepseek-v4-pro                       # 规划
export ANALYST_MODEL=deepseek-v4-flash                     # 市场/新闻/板块/顾问
export REVIEWER_MODEL=kimi-k2.6                            # 主编终审
export EMAIL_SMTP_HOST=smtp.qq.com EMAIL_SMTP_PORT=587 EMAIL_FROM=... EMAIL_PASSWORD=...
export TIMER_SECRET=$(openssl rand -hex 16)
```
> 模型名必须与供应商 API 实际型号一致（可用 `GET /v1/models` 查 Moonshot 型号；
> Moonshot 的 2.7 仅有 code 版，通用写作建议用 `kimi-k2.6`）。
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
