# Pusher-Go Advanced 设计文档

> 日期: 2026-06-25
> 状态: 草稿 v2
> 修订: v2 — 后端改 Python/FastAPI、数据源改免费库(akshare/efinance/yfinance)、流水线改异步 job、SCF 改 Web 函数、持仓加 market 字段与可选数量

## 0. v2 变更摘要

相对 v1（初稿）的关键决策：

| 维度 | v1 | v2（本文） |
|------|------|--------|
| 后端语言 | Go | **Python (FastAPI)** |
| SCF 形态 | 事件函数 + 手写 Router | **Web 函数（标准 HTTP server）** |
| 数据源 | Tushare Pro（需积分） | **akshare(主) + efinance(降级) + yfinance(港美股)**，全免费 |
| 流水线执行 | 同步，60s 超时 | **异步 job + CLI 轮询**（新增 `jobs` 表） |
| 函数内存 | 128–256MB | **512MB–1024MB**（pandas/akshare 需求） |
| 部署 | 直接上传 | **COS / Layer 分层**（依赖包体积超 50MB） |
| 用户规模 | 未定 | **个位数**，per-user Agent 内联并行即可 |
| 持仓 | quantity/cost | 加 **market 字段**(cn/hk/us)；quantity/cost **可选**，占比派生 |

## 1. 概述

基于 [pusher-go](https://github.com/chriscco/pusher-go) 的全面升级。将原本基于 GNews API + DeepSeek 简单总结 + 邮件推送的单用户 cron 任务，升级为部署在腾讯云 SCF 上的多触发器服务化架构，配套 Rust CLI 客户端。

### 核心升级点

- RSS 聚合替代 GNews API，提升新闻可信度和自定义程度
- 集成免费金融数据库（akshare / efinance / yfinance），覆盖 A 股大盘、个股、板块、基金持仓、港美股
- 引入 MySQL 数据库，支持多用户、持仓管理、历史报告
- AI 层从"一次简单总结"升级为多 Agent 协作流水线（Planner → Analysts → Reviewer）
- 腾讯云 SCF 部署（Python Web 函数），Timer 定时触发 + API Gateway HTTP 触发双模式
- 流水线异步执行：触发即返回 job_id，后台跑，客户端轮询
- Rust CLI 跨平台客户端

## 2. 架构

### 2.1 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│              腾讯云 SCF (Python Web 函数, 单函数双触发)             │
│                                                                  │
│  ┌─────────────────┐     ┌────────────────────────────────────┐  │
│  │  API Gateway     │     │  Timer Trigger                     │  │
│  │  (HTTPS 手动触发) │     │  (每天定时 8:00 北京)              │  │
│  └────────┬─────────┘     └──────────┬─────────────────────────┘  │
│           │  HTTP 请求               │  POST /internal/timer       │
│           ▼                          ▼                            │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │              FastAPI App (ASGI, 标准路由)                │     │
│  └───────────────────────┬─────────────────────────────────┘     │
│                          │                                        │
│      ┌───────────────────┼───────────────────┐                   │
│      ▼                   ▼                   ▼                   │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐         │
│  │ User/Auth  │  │ Job API      │  │ Report API        │         │
│  │ Portfolio  │  │ 入队/查状态  │  │ 查历史报告        │         │
│  └─────┬──────┘  └──────┬───────┘  └────────┬─────────┘         │
│        │                │ 入队             │                     │
│        │                ▼                  │                     │
│        │        ┌───────────────┐          │                     │
│        │        │ Pipeline      │  后台异步执行                  │
│        │        │ 采集→AI→邮件  │  (job: pending→running→done)   │
│        │        └───────┬───────┘                                │
│        └────────────────┼──────────────────┘                    │
│                         ▼                                        │
│              ┌──────────────────┐                               │
│              │    MySQL CDB     │  users / portfolios            │
│              │                  │  fund_holdings / reports       │
│              │                  │  rss_sources / jobs            │
│              └──────────────────┘                               │
├──────────────────────────────────────────────────────────────────┤
│  数据源(免费)         │  LLM            │  推送                   │
│  akshare  (A股/板块)  │  DeepSeek 默认  │  邮件 SMTP             │
│  efinance (降级备份)  │  可选 Claude/GPT│                        │
│  yfinance (港美股)    │                 │                        │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 技术选型

| 组件 | 技术 | 理由 |
|------|------|------|
| 云函数 | Python + Tencent SCF Web 函数 | 数据层依赖 Python 库，单语言最简 |
| Web 框架 | FastAPI (ASGI) | 路由清晰，自带校验，SCF Web 函数兼容 |
| 客户端 | Rust | 用户指定，交叉编译友好 |
| 数据库 | 腾讯云 MySQL (CDB) | 关系型数据，部署方便 |
| 新闻源 | RSS (feedparser) | 可信度高，可定制，免费 |
| 金融数据 | akshare(主) / efinance(降级) / yfinance(港美股) | 全免费，无积分门槛 |
| LLM | DeepSeek (默认) + 可选 Claude/GPT | 通过环境变量配置，支持用户自定义 |
| 异步执行 | SCF 内后台任务 + jobs 表状态机 | 规避 60s/网关超时 |

### 2.3 数据源策略（重要）

akshare / efinance 走的是东方财富、新浪等的**非官方接口**，在云函数固定出口 IP 上存在被限流/封禁、接口结构变动导致抓取失败的风险。因此：

- 统一抽象 `MarketDataProvider` 接口，按标的 `market` 路由：
  - `cn`（A 股/国内基金）→ akshare，失败降级 efinance
  - `hk` / `us`（港美股）→ yfinance
- 每个数据任务都必须：**重试（指数退避）→ 降级备份源 → 当日缓存 → 优雅缺数据**（缺数据时报告对应段落标注"数据暂不可用"，不让整条流水线失败）。
- 当日已抓取的数据写入缓存（同进程内存 / 临时表），避免同一天重复抓取触发限流。

## 3. 数据库设计

### 3.1 users

```sql
CREATE TABLE users (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    email       VARCHAR(255) NOT NULL UNIQUE,
    password    VARCHAR(255) NOT NULL,        -- bcrypt 加密
    model_key   VARCHAR(255) DEFAULT NULL,     -- 用户自定义 API Key (预留)
    model_name  VARCHAR(64) DEFAULT NULL,      -- 用户自定义模型名 (预留)
    model_endpoint VARCHAR(255) DEFAULT NULL,  -- 用户自定义端点 (预留)
    email_to    VARCHAR(255) NOT NULL,         -- 报告推送邮箱
    token       VARCHAR(128) NOT NULL,         -- CLI 登录令牌（单一长期 token）
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

> 认证语义：单一长期 token，login 覆盖同列（第二台设备登录会顶掉第一台）。MVP 可接受，无过期/刷新机制。

### 3.2 portfolios

```sql
CREATE TABLE portfolios (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    symbol      VARCHAR(32) NOT NULL,          -- 股票/基金代码
    name        VARCHAR(128),                  -- 名称
    type        ENUM('stock', 'fund') NOT NULL,
    market      ENUM('cn', 'hk', 'us') NOT NULL DEFAULT 'cn',  -- 决定数据源路由
    quantity    DECIMAL(16,4) DEFAULT NULL,    -- 持有数量/份额（可选）
    cost_price  DECIMAL(10,4) DEFAULT NULL,    -- 成本价（可选）
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user (user_id)
);
```

> **持仓占比不入库、不手填**：由 `quantity × 当日价` 计算每支市值，再除以用户总市值派生。
> - 用户填了 `quantity` → 个人顾问 Agent 做**加权分析**（占比、集中度、配合 `cost_price` 算盈亏）。
> - 未填 `quantity` → 退化为"自选股"等权模式。

### 3.3 fund_holdings

```sql
CREATE TABLE fund_holdings (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    fund_code   VARCHAR(32) NOT NULL,
    stock_code  VARCHAR(32) NOT NULL,
    stock_name  VARCHAR(128),
    ratio       DECIMAL(5,2),                 -- 持仓占比 %
    quarter     VARCHAR(16) NOT NULL,          -- 季度 e.g. 2026Q2
    updated_at  DATE NOT NULL,
    INDEX idx_fund (fund_code, quarter)
);
```

> 数据来源：akshare `fund_portfolio_hold_em`（或 efinance 降级），仅国内基金。

### 3.4 reports

```sql
CREATE TABLE reports (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    report_date     DATE NOT NULL,
    content         TEXT,                     -- 报告全文 (HTML)
    news_summary    TEXT,                     -- 新闻摘要
    stock_summary   TEXT,                     -- 大盘行情摘要
    personal_analysis TEXT,                   -- 个性化持仓分析
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user_date (user_id, report_date)
);
```

> 注：市场/新闻/板块为共享段落，按 user_id 存会在每个用户行重复。个位数用户规模下可接受，暂不拆分共享表（列入未尽事项）。

### 3.5 rss_sources

```sql
CREATE TABLE rss_sources (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(128),
    url         VARCHAR(512) NOT NULL,
    category    VARCHAR(64),                   -- business / tech / world
    lang        VARCHAR(8) DEFAULT 'zh',
    enabled     BOOLEAN DEFAULT TRUE,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 3.6 jobs（新增）

```sql
CREATE TABLE jobs (
    id          VARCHAR(36) PRIMARY KEY,       -- UUID
    user_id     INT DEFAULT NULL,              -- 手动触发归属用户；timer 全量为 NULL
    type        ENUM('pipeline', 'manual_report') NOT NULL,
    status      ENUM('pending', 'running', 'done', 'failed') NOT NULL DEFAULT 'pending',
    error       TEXT DEFAULT NULL,             -- failed 时的错误信息
    report_date DATE DEFAULT NULL,             -- 完成后指向生成的报告日期
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME DEFAULT NULL,
    INDEX idx_user (user_id),
    INDEX idx_status (status)
);
```

> 异步执行核心：`/trigger-report` 创建 job 返回 `job_id` 后立即响应；后台任务推进 `pending → running → done/failed`；CLI 轮询 `GET /job/:id`。

## 4. 数据流水线设计

### 4.1 数据采集阶段（纯逻辑，无 AI）

```
Timer 触发 (每天 8:00 北京时间) / 手动 job
   │
   ├── 1. 遍历 rss_sources，并发拉取 RSS (feedparser)
   │     去重规则: 标题 + URL 哈希
   │     限流: 每源最多 5 条
   │
   ├── 2. 大盘数据 (akshare)
   │     上证指数、深证成指、创业板指 当日行情
   │
   ├── 3. 个股行情
   │     查询所有用户持仓股票代码（去重），按 market 路由:
   │       cn → akshare（降级 efinance）；hk/us → yfinance
   │
   ├── 4. 板块数据 (akshare)
   │     行业板块涨跌排行、资金流向
   │
   └── 5. 基金持仓刷新 (按季度, akshare fund_portfolio_hold_em)
         每季度首次运行时，遍历所有用户持有的 fund 类型(market=cn)
         查最新季度持仓，写入 fund_holdings

每个采集步骤遵循 §2.3 的"重试→降级→缓存→优雅缺数据"。
```

### 4.2 Agentic AI 流水线

```
Phase 2: Planner AI
──────────────
Prompt: 当日核心事件 + 全部用户持仓概览
任务: 规划今日报告大纲，标注每个用户的关注重点
模型: DeepSeek-R1 / Claude（需推理能力）
调用: 1 次

Phase 3: 并行 Agent
──────────────
Agent A - 市场分析师
  输入: 大盘 + 板块数据
  输出: 市场概览段落
  模型: DeepSeek-chat（便宜）

Agent B - 新闻编辑
  输入: RSS 聚合结果
  输出: TOP 5-8 精选新闻 + 简短点评
  模型: DeepSeek-chat

Agent C - 板块轮动分析
  输入: 板块涨跌排行 + 资金流向
  输出: 板块热点分析
  模型: DeepSeek-chat

Agent D/E/... - 个人顾问（按用户并行，个位数用户内联即可）
  输入: 该用户持仓 + 当日行情 + 持仓相关新闻
        + 若有 quantity → 派生占比/集中度（+cost_price → 盈亏）
  输出: 个性化涨跌分析 + 简要建议
  模型: 默认 DeepSeek-chat（可配置更贵模型）

Phase 4: Reviewer AI
──────────────
输入: 以上所有 Agent 的输出
任务: 整合为一篇连贯报告，检查数据一致性，优化文风
输出: 完整 HTML 报告
模型: DeepSeek-chat
```

### 4.3 模型配置层级

```
环境变量 (默认，系统级):
  DEEPSEEK_API_KEY=sk-xxx
  DEEPSEEK_MODEL=deepseek-chat
  PLANNER_MODEL=deepseek-r1

用户级 (预留，未启用):
  users.model_key         — 覆盖环境变量
  users.model_name        — 覆盖模型名
  users.model_endpoint    — 覆盖 API 端点

代码逻辑:
  if user.model_key != "" → 用用户的 Key + 模型
  else                   → 用环境变量默认配置
```

## 5. API 设计

### 5.1 路由表

| 方法 | 路径 | 认证 | 描述 |
|------|------|------|------|
| POST | /register | 否 | 用户注册（邮箱+密码）→ 返回 token |
| POST | /login | 否 | 用户登录 → 返回 token |
| POST | /portfolio | Bearer | 添加持仓（symbol/type/market，quantity/cost 可选） |
| DELETE | /portfolio/:id | Bearer | 删除持仓 |
| GET | /portfolio | Bearer | 列出所有持仓 |
| GET | /report/today | Bearer | 获取今日报告 |
| GET | /report/:date | Bearer | 获取指定日期报告 |
| GET | /report/list | Bearer | 列出历史报告日期 |
| POST | /trigger-report | Bearer | 手动触发流水线 → 返回 job_id（异步） |
| GET | /job/:id | Bearer | 查询 job 状态（pending/running/done/failed） |
| POST | /internal/timer | 内部 | Timer 触发入口，入队全量 pipeline job |

### 5.2 Timer 触发器

- 定时规则: SCF 7 段 cron `0 0 8 * * * *`（秒 分 时 日 月 周 年，每天北京时间 8:00；SCF 触发器默认 UTC+8，部署时确认）
- Timer 入口创建全量 `pipeline` job 后立即返回；流水线在后台异步执行：数据采集 → Agentic AI → 邮件推送。

### 5.3 异步执行约定

- `POST /trigger-report`：创建 `manual_report` job（归属当前用户），返回 `{ "job_id": "..." }`，HTTP 立即响应，规避 API 网关响应超时。
- 后台任务推进状态机；完成后 `jobs.report_date` 指向生成的报告。
- CLI `trigger run` 拿到 job_id 后轮询 `GET /job/:id` 直到 `done/failed`。

## 6. Rust CLI 设计

### 6.1 命令定义

```
pusher register --email <email>        交互式输入密码 → 注册并登录
pusher login --email <email>           交互式输入密码 → 登录
pusher logout                          清除本地 token

pusher portfolio add-stock <code> [--market cn|hk|us] [--quantity <n>] [--cost <price>]
pusher portfolio add-fund <code>  [--quantity <n>] [--cost <price>]   # 基金默认 market=cn
pusher portfolio remove <id>          删除持仓
pusher portfolio list                 查看所有持仓（含派生占比，若有数量）

pusher report today                   拉取今日报告
pusher report get <date>              查询历史某天报告
pusher report list                    列出已有报告

pusher trigger run                    手动触发流水线 → 返回 job_id 并轮询状态至完成
```

> `--quantity`/`--cost` 可选；不填即自选股等权模式。`add-stock` 默认 `--market cn`。

### 6.2 本地配置

```toml
# ~/.pusher/config.toml
[server]
endpoint = "https://xxx.apigw.tencentcs.com"

[auth]
token = "xxx"
email = "xxx@xxx.com"

[defaults]
timezone = "Asia/Shanghai"
```

### 6.3 跨平台编译

```bash
# macOS (Apple Silicon)
cargo build --target aarch64-apple-darwin --release
# macOS (Intel)
cargo build --target x86_64-apple-darwin --release
# Linux
cargo build --target x86_64-unknown-linux-gnu --release
# Windows
cargo build --target x86_64-pc-windows-gnu --release
```

## 7. 部署架构

### 7.1 腾讯云资源清单

| 资源 | 规格 | 用途 |
|------|------|------|
| SCF 函数 | **512MB–1024MB**, **300–600s 超时**, Python Web 函数 | 后端 + 异步流水线 |
| API 网关 | HTTPS | CLI 的 HTTP 入口 |
| Timer 触发器 | 每天 8:00（UTC+8） | 定时流水线 |
| MySQL CDB | 最小配置（1核1G） | 用户/持仓/报告/job 数据 |
| COS 存储桶 | 标准 | 存放依赖分层包（部署用） |

> 内存：pandas/akshare 起步需求高，128–256MB 不够。
> 部署：akshare+pandas+numpy 解压上百 MB，超过 SCF 直接上传 50MB 限制，依赖通过 COS / Layer 分层。
> 数据库连接：SCF 多实例并发会放大连接数，全局复用单连接/小连接池，设上限避免 CDB `max_connections` 耗尽。

### 7.2 SCF 环境变量

```
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-chat
PLANNER_MODEL=deepseek-r1
MYSQL_HOST=xxx.cdb.tencentcdb.com
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=xxx
MYSQL_DATABASE=pusher
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_FROM=xxx@gmail.com
EMAIL_PASSWORD=xxx
```

> 注：不再需要 TUSHARE_TOKEN（数据源改免费库）。

## 8. 项目结构

```
pusher-go-advanced/
├── server/                    # Python SCF Web 函数
│   ├── app/
│   │   ├── main.py            # FastAPI 入口, 路由挂载
│   │   ├── config.py          # 环境变量读取
│   │   ├── api/
│   │   │   ├── auth.py        # 注册/登录
│   │   │   ├── portfolio.py   # 持仓管理
│   │   │   ├── report.py      # 报告查询
│   │   │   ├── job.py         # 触发 + job 状态
│   │   │   └── timer.py       # /internal/timer 入口
│   │   ├── pipeline/
│   │   │   ├── pipeline.py    # 主流水线编排（异步）
│   │   │   ├── rss.py         # RSS 采集 (feedparser)
│   │   │   ├── email.py       # 邮件发送
│   │   │   └── fund.py        # 基金持仓刷新
│   │   ├── data/
│   │   │   ├── provider.py    # MarketDataProvider 抽象 + 路由/降级/缓存
│   │   │   ├── ak.py          # akshare 实现（A股/板块/基金）
│   │   │   ├── ef.py          # efinance 降级实现
│   │   │   └── yf.py          # yfinance 实现（港美股）
│   │   ├── agents/
│   │   │   ├── planner.py     # Planner Agent
│   │   │   ├── analyst.py     # 市场分析 Agent
│   │   │   ├── editor.py      # 新闻编辑 Agent
│   │   │   ├── sector.py      # 板块轮动 Agent
│   │   │   ├── advisor.py     # 个人顾问 Agent
│   │   │   ├── reviewer.py    # 主编审稿 Agent
│   │   │   └── llm.py         # LLM 客户端封装（模型配置层级）
│   │   ├── models/
│   │   │   ├── user.py
│   │   │   ├── portfolio.py
│   │   │   ├── report.py
│   │   │   └── job.py
│   │   └── db/
│   │       └── mysql.py       # 数据库连接（全局复用）
│   ├── requirements.txt
│   └── scf_bootstrap          # Web 函数启动脚本（拉起 uvicorn）
│
├── cli/                       # Rust CLI
│   ├── Cargo.toml
│   └── src/
│       ├── main.rs
│       ├── commands/
│       │   ├── auth.rs
│       │   ├── portfolio.rs
│       │   ├── report.rs
│       │   └── trigger.rs
│       ├── config.rs
│       └── api.rs
│
├── deploy/                    # 部署配置
│   └── scf.yaml               # SCF 部署配置文件（Web 函数 + COS 分层）
│
├── sql/
│   └── schema.sql             # 数据库建表脚本（含 jobs 表）
│
└── docs/
    └── superpowers/specs/
        └── 2026-06-25-pusher-go-advanced-design.md
```

## 9. 安全考虑

- 密码使用 bcrypt 加密存储
- CLI Token 是随机生成的 128 字符字符串（单一长期 token，无过期）
- API Key 存储在 SCF 环境变量，不进入代码仓库
- `users.model_key`（用户自配 Key，预留）为明文入库，启用前需评估加密
- 数据库只允许 SCF 函数在白名单内访问（腾讯云安全组）
- `/internal/timer` 仅供 Timer 触发器内部使用，需鉴权或网络隔离，避免被公网直接调用

## 10. 未尽事项（后续迭代）

- 基金持仓自动刷新机制（每季度触发一次 vs 每次运行检查"首次运行"标记）
- 免费数据源稳定性兜底（akshare/efinance 接口变动或封禁时的二级降级、告警）
- 报告共享段落与个性化段落拆表，消除多用户 TEXT 冗余
- RSS 源管理 API（目前通过 SQL 手动添加）
- 报告模板的自定义（用户自己选择报告风格）
- CLI 的自动更新机制
- 多设备 token / token 过期与刷新机制
