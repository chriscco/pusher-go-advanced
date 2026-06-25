# Pusher-Go Advanced 设计文档

> 日期: 2026-06-25
> 状态: 草稿

## 1. 概述

基于 [pusher-go](https://github.com/chriscco/pusher-go) 的全面升级。将原本基于 GNews API + DeepSeek 简单总结 + 邮件推送的单用户 cron 任务，升级为部署在腾讯云 SCF 上的多触发器服务化架构，配套 Rust CLI 客户端。

### 核心升级点

- RSS 聚合替代 GNews API，提升新闻可信度和自定义程度
- 集成 Tushare 股票数据，覆盖大盘、个股、板块、基金持仓
- 引入 MySQL 数据库，支持多用户、持仓管理、历史报告
- AI 层从"一次简单总结"升级为多 Agent 协作流水线（Planner → Analysts → Reviewer）
- 腾讯云 SCF 部署，Timer 定时触发 + API Gateway HTTP 触发双模式
- Rust CLI 跨平台客户端

## 2. 架构

### 2.1 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                   腾讯云 SCF (单函数双触发)                       │
│                                                                  │
│  ┌─────────────────┐     ┌────────────────────────────────────┐  │
│  │  API Gateway     │     │  Timer Trigger                     │  │
│  │  (HTTP 手动触发)  │     │  (每天定时 8:00)                   │  │
│  └────────┬─────────┘     └──────────┬─────────────────────────┘  │
│           │                          │                            │
│           ▼                          ▼                            │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │                    Router                               │     │
│  │  判断来源: timer → 跑流水线, HTTP → 按 path 路由       │     │
│  └───────────────────────┬─────────────────────────────────┘     │
│                          │                                        │
│          ┌───────────────┼───────────────┐                       │
│          ▼               ▼               ▼                       │
│  ┌────────────┐  ┌──────────────┐  ┌──────────┐                │
│  │ User API   │  │ Pipeline     │  │ Report    │                │
│  │ 注册/登录  │  │ RSS+Tushare  │  │ 查历史    │                │
│  │ 配置持仓   │  │ +Agentic AI  │  │ 生成报告  │                │
│  │            │  │ +邮件推送    │  │           │                │
│  └─────┬──────┘  └──────┬───────┘  └────┬─────┘                │
│        │                │               │                        │
│        └────────────────┼───────────────┘                       │
│                         ▼                                        │
│              ┌──────────────────┐                               │
│              │    MySQL CDB     │                               │
│              │  users           │                               │
│              │  portfolios      │                               │
│              │  fund_holdings   │                               │
│              │  reports         │                               │
│              │  rss_sources     │                               │
│              └──────────────────┘                               │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────┐     ┌──────────────┐     ┌───────────────┐  │
│  │ Rust CLI       │ ←─→ │ API Gateway  │     │ 邮件 (SMTP)   │  │
│  │ (mac/linux/win)│     │ (HTTPS)      │     │ 推送报告       │  │
│  └────────────────┘     └──────────────┘     └───────────────┘  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 技术选型

| 组件 | 技术 | 理由 |
|------|------|------|
| 云函数 | Go + Tencent SCF | 与原项目一致，SCF Go Runtime 成熟 |
| 客户端 | Rust | 用户指定，交叉编译友好 |
| 数据库 | 腾讯云 MySQL (CDB) | 关系型数据，部署方便 |
| 新闻源 | RSS | 可信度高，可定制，免费 |
| 股票数据 | Tushare Pro | 覆盖 A 股/港股/基金持仓 |
| LLM | DeepSeek (默认) + 可选 Claude/GPT | 通过环境变量配置，支持用户自定义 |

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
    token       VARCHAR(128) NOT NULL,         -- CLI 登录令牌
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 3.2 portfolios

```sql
CREATE TABLE portfolios (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    symbol      VARCHAR(32) NOT NULL,          -- 股票/基金代码
    name        VARCHAR(128),                  -- 名称
    type        ENUM('stock', 'fund') NOT NULL,
    quantity    DECIMAL(16,4),                -- 持有数量/份额
    cost_price  DECIMAL(10,4),                -- 成本价（可选）
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user (user_id)
);
```

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

## 4. 数据流水线设计

### 4.1 数据采集阶段（纯逻辑，无 AI）

```
Timer 触发 (每天 8:00 北京时间)
   │
   ├── 1. 遍历 rss_sources，并发拉取 RSS
   │     去重规则: 标题 + URL 哈希
   │     限流: 每源最多 5 条
   │
   ├── 2. Tushare 大盘数据
   │     上证指数、深证成指、创业板指 当日行情
   │
   ├── 3. Tushare 个股行情
   │     查询所有用户持仓的股票代码（去重后），取当日行情
   │
   ├── 4. Tushare 板块数据
   │     行业板块涨跌排行、资金流向
   │
   └── 5. 基金持仓刷新 (按季度)
         每季度首次运行时，遍历所有用户持有的 fund 类型
         通过 Tushare 查最新季度持仓，写入 fund_holdings
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
  输入: Tushare 大盘 + 板块数据
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

Agent D/E/... - 个人顾问（按用户并行）
  输入: 该用户持仓 + 当日行情 + 持仓相关新闻
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
| POST | /portfolio | Bearer | 添加持仓 |
| DELETE | /portfolio/:id | Bearer | 删除持仓 |
| GET | /portfolio | Bearer | 列出所有持仓 |
| GET | /report/today | Bearer | 获取今日报告 |
| GET | /report/:date | Bearer | 获取指定日期报告 |
| GET | /report/list | Bearer | 列出历史报告日期 |
| POST | /trigger-report | Bearer | 手动触发一次流水线 |

### 5.2 Timer 触发器

- 定时规则: `0 0 8 * * *` (每天北京时间 8:00)
- 内部执行完整流水线: 数据采集 → Agentic AI → 邮件推送

## 6. Rust CLI 设计

### 6.1 命令定义

```
pusher register --email <email>        交互式输入密码 → 注册并登录
pusher login --email <email>           交互式输入密码 → 登录
pusher logout                          清除本地 token

pusher portfolio add-stock <code>     添加股票持仓
pusher portfolio add-fund <code>      添加基金持仓
pusher portfolio remove <id>          删除持仓
pusher portfolio list                 查看所有持仓

pusher report today                   拉取今日报告
pusher report get <date>              查询历史某天报告
pusher report list                    列出已有报告

pusher trigger run                    手动触发流水线
```

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
| SCF 函数 | 128MB-256MB, 60s 超时 | Go 后端 |
| API 网关 | HTTPS | CLI 的 HTTP 入口 |
| Timer 触发器 | 每天 8:00 | 定时流水线 |
| MySQL CDB | 最小配置（1核1G） | 用户/持仓/报告数据 |

### 7.2 SCF 环境变量

```
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-chat
PLANNER_MODEL=deepseek-r1
TUSHARE_TOKEN=xxx
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

## 8. 项目结构

```
pusher-go-advanced/
├── server/                    # Go SCF 函数
│   ├── main.go                # 入口, router
│   ├── go.mod
│   ├── go.sum
│   ├── handler/
│   │   ├── auth.go            # 注册/登录
│   │   ├── portfolio.go       # 持仓管理
│   │   ├── report.go          # 报告查询
│   │   └── trigger.go         # 手动触发
│   ├── pipeline/
│   │   ├── pipeline.go        # 主流水线编排
│   │   ├── rss.go             # RSS 采集
│   │   ├── tushare.go         # Tushare 数据
│   │   ├── fund.go            # 基金持仓
│   │   └── email.go           # 邮件发送
│   ├── agent/
│   │   ├── planner.go         # Planner Agent
│   │   ├── analyst.go         # 分析 Agent
│   │   ├── editor.go          # 新闻编辑 Agent
│   │   ├── advisor.go         # 个人顾问 Agent
│   │   └── reviewer.go        # 主编审稿 Agent
│   ├── model/
│   │   ├── user.go
│   │   ├── portfolio.go
│   │   ├── report.go
│   │   └── news.go
│   ├── db/
│   │   └── mysql.go           # 数据库连接
│   └── config/
│       └── config.go          # 环境变量读取
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
│   └── scf.yaml               # SCF 部署配置文件
│
├── sql/
│   └── schema.sql             # 数据库建表脚本
│
└── docs/
    └── superpowers/specs/
        └── 2026-06-25-pusher-go-advanced-design.md
```

## 9. 安全考虑

- 密码使用 bcrypt 加密存储
- CLI Token 是随机生成的 128 字符字符串
- API Key 存储在 SCF 环境变量，不进入代码仓库
- 数据库只允许 SCF 函数在白名单内访问（腾讯云安全组）
- 预留用户自配 Key 功能但不强制使用

## 10. 未尽事项（后续迭代）

- 基金持仓自动刷新机制（每季度触发一次 vs 每次运行检查）
- RSS 源管理 API（目前通过 SQL 手动添加）
- 报告模板的自定义（用户自己选择报告风格）
- CLI 的自动更新机制
