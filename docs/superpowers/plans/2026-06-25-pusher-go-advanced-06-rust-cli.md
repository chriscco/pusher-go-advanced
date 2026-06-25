# Pusher-Go Advanced — 子计划 6: Rust CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现跨平台 Rust CLI `pusher`：注册/登录/登出、持仓增删查、报告查询、手动触发并轮询，本地 token 配置存于 `~/.pusher/config.toml`。

**Architecture:** `config.rs` 读写本地配置；`api.rs` 是 HTTP 客户端（reqwest blocking + serde）；`commands/` 各子命令薄封装；`main.rs` 用 clap 解析并分发。配置与 API 逻辑用单元测试覆盖，API 测试打本地 `httpmock` 模拟服务，不依赖真实后端。

**Tech Stack:** Rust（2021 edition）、clap（derive）、reqwest（blocking, rustls）、serde/serde_json、toml、rpassword、dirs、anyhow，测试用 httpmock。

## Global Constraints

- 所有 HTTP 通过 `api::Api`，统一处理 `Authorization: Bearer <token>` 与错误。
- 端点解析优先级：`--endpoint` 全局参数 > 环境变量 `PUSHER_ENDPOINT` > 配置文件 `server.endpoint`；都没有则报错提示先设置。
- 密码经 `rpassword` 交互输入，绝不作为命令行参数。
- 配置文件路径：`~/.pusher/config.toml`（`dirs::home_dir()` 拼接）。
- API 测试一律用 httpmock 本地服务，不打真实网络。

---

## File Structure

- `cli/Cargo.toml` — 包与依赖。
- `cli/src/main.rs` — clap 定义 + 分发。
- `cli/src/config.rs` — 配置读写。
- `cli/src/api.rs` — HTTP 客户端 + 数据结构。
- `cli/src/commands/mod.rs` — 子模块声明。
- `cli/src/commands/auth.rs`、`portfolio.rs`、`report.rs`、`trigger.rs` — 命令实现。

---

## Task 1: Cargo 脚手架 + 配置模块

**Files:**
- Create: `cli/Cargo.toml`, `cli/src/main.rs`（临时占位）, `cli/src/config.rs`

**Interfaces:**
- Produces:
  - `config::Config { server: Server, auth: Auth }`，`Server { endpoint: String }`，`Auth { token: String, email: String }`，均 `Serialize + Deserialize + Default + Clone`。
  - `config::config_path() -> PathBuf`（`~/.pusher/config.toml`）。
  - `config::Config::load() -> Config`（文件不存在返回 `Default`）。
  - `config::Config::save(&self) -> anyhow::Result<()>`（自动建目录）。
  - `config::Config::load_from(path: &Path) -> Config` / `save_to(&self, path: &Path)`（供测试注入路径）。

- [ ] **Step 1: 写 Cargo.toml**

Create `cli/Cargo.toml`:

```toml
[package]
name = "pusher"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "pusher"
path = "src/main.rs"

[dependencies]
clap = { version = "4.5", features = ["derive"] }
reqwest = { version = "0.12", default-features = false, features = ["blocking", "json", "rustls-tls"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
toml = "0.8"
rpassword = "7"
dirs = "5"
anyhow = "1"

[dev-dependencies]
httpmock = "0.7"
tempfile = "3"
```

- [ ] **Step 2: 临时 main 占位（让 crate 可编译）**

Create `cli/src/main.rs`:

```rust
mod config;

fn main() {
    println!("pusher");
}
```

- [ ] **Step 3: 写失败测试**

Create `cli/src/config.rs`:

```rust
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub struct Server {
    pub endpoint: String,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub struct Auth {
    pub token: String,
    pub email: String,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub struct Config {
    #[serde(default)]
    pub server: Server,
    #[serde(default)]
    pub auth: Auth,
}

pub fn config_path() -> PathBuf {
    let mut p = dirs::home_dir().unwrap_or_else(|| PathBuf::from("."));
    p.push(".pusher");
    p.push("config.toml");
    p
}

impl Config {
    pub fn load() -> Config {
        Config::load_from(&config_path())
    }

    pub fn load_from(path: &Path) -> Config {
        match std::fs::read_to_string(path) {
            Ok(s) => toml::from_str(&s).unwrap_or_default(),
            Err(_) => Config::default(),
        }
    }

    pub fn save(&self) -> anyhow::Result<()> {
        self.save_to(&config_path())
    }

    pub fn save_to(&self, path: &Path) -> anyhow::Result<()> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(path, toml::to_string_pretty(self)?)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn load_missing_returns_default() {
        let p = std::path::Path::new("/nonexistent/pusher/config.toml");
        let c = Config::load_from(p);
        assert_eq!(c.auth.token, "");
    }

    #[test]
    fn save_and_load_roundtrip() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("config.toml");
        let mut c = Config::default();
        c.server.endpoint = "https://api.example.com".into();
        c.auth.token = "tok123".into();
        c.auth.email = "u@x.com".into();
        c.save_to(&path).unwrap();

        let loaded = Config::load_from(&path);
        assert_eq!(loaded.server.endpoint, "https://api.example.com");
        assert_eq!(loaded.auth.token, "tok123");
        assert_eq!(loaded.auth.email, "u@x.com");
    }
}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd cli && cargo test config -- --nocapture`
Expected: PASS（2 passed）。首次编译会拉依赖，耗时较长属正常。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add cli/Cargo.toml cli/src/main.rs cli/src/config.rs
git commit -m "feat(cli): scaffold cargo project and config module"
```

---

## Task 2: API 客户端（注册/登录）

**Files:**
- Create: `cli/src/api.rs`
- Modify: `cli/src/main.rs`（`mod api;`）

**Interfaces:**
- Produces:
  - `api::Api { endpoint: String, token: Option<String> }`，`Api::new(endpoint, token)`。
  - `api::Api::register(&self, email: &str, password: &str) -> anyhow::Result<String>`（返回 token）。
  - `api::Api::login(&self, email: &str, password: &str) -> anyhow::Result<String>`。
  - 内部 `fn post_json(&self, path, body) -> Result<serde_json::Value>`，非 2xx 时返回 `Err`（含状态码与响应体）。

- [ ] **Step 1: 写 api.rs（含失败测试）**

Create `cli/src/api.rs`:

```rust
use anyhow::{anyhow, Result};
use serde_json::{json, Value};

pub struct Api {
    pub endpoint: String,
    pub token: Option<String>,
}

impl Api {
    pub fn new(endpoint: impl Into<String>, token: Option<String>) -> Self {
        Api { endpoint: endpoint.into(), token }
    }

    fn url(&self, path: &str) -> String {
        format!("{}{}", self.endpoint.trim_end_matches('/'), path)
    }

    fn client(&self) -> reqwest::blocking::Client {
        reqwest::blocking::Client::new()
    }

    fn post_json(&self, path: &str, body: Value) -> Result<Value> {
        let mut req = self.client().post(self.url(path)).json(&body);
        if let Some(t) = &self.token {
            req = req.bearer_auth(t);
        }
        let resp = req.send()?;
        let status = resp.status();
        let text = resp.text().unwrap_or_default();
        if !status.is_success() {
            return Err(anyhow!("HTTP {}: {}", status.as_u16(), text));
        }
        Ok(serde_json::from_str(&text).unwrap_or(Value::Null))
    }

    pub fn register(&self, email: &str, password: &str) -> Result<String> {
        let v = self.post_json("/register", json!({"email": email, "password": password}))?;
        v["token"].as_str().map(String::from)
            .ok_or_else(|| anyhow!("no token in response"))
    }

    pub fn login(&self, email: &str, password: &str) -> Result<String> {
        let v = self.post_json("/login", json!({"email": email, "password": password}))?;
        v["token"].as_str().map(String::from)
            .ok_or_else(|| anyhow!("no token in response"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use httpmock::prelude::*;

    #[test]
    fn login_returns_token() {
        let server = MockServer::start();
        let m = server.mock(|when, then| {
            when.method(POST).path("/login");
            then.status(200).json_body(serde_json::json!({"token": "abc"}));
        });
        let api = Api::new(server.base_url(), None);
        let tok = api.login("u@x.com", "pw").unwrap();
        m.assert();
        assert_eq!(tok, "abc");
    }

    #[test]
    fn login_failure_is_err() {
        let server = MockServer::start();
        server.mock(|when, then| {
            when.method(POST).path("/login");
            then.status(401).json_body(serde_json::json!({"detail": "bad"}));
        });
        let api = Api::new(server.base_url(), None);
        assert!(api.login("u@x.com", "wrong").is_err());
    }

    #[test]
    fn register_returns_token() {
        let server = MockServer::start();
        server.mock(|when, then| {
            when.method(POST).path("/register");
            then.status(201).json_body(serde_json::json!({"token": "newtok"}));
        });
        let api = Api::new(server.base_url(), None);
        assert_eq!(api.register("u@x.com", "pw").unwrap(), "newtok");
    }
}
```

- [ ] **Step 2: 声明模块**

Edit `cli/src/main.rs`：

```rust
mod api;
mod config;

fn main() {
    println!("pusher");
}
```

- [ ] **Step 3: 运行测试，确认通过**

Run: `cd cli && cargo test api -- --nocapture`
Expected: PASS（3 passed）。

- [ ] **Step 4: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add cli/src/api.rs cli/src/main.rs
git commit -m "feat(cli): add api client with register/login"
```

---

## Task 3: 持仓 / 报告 / 触发 API 方法

**Files:**
- Modify: `cli/src/api.rs`（新增方法 + 数据结构 + 测试）

**Interfaces:**
- Produces（追加到 `Api`）：
  - `Holding { id: i64, symbol, name: Option<String>, r#type: String, market: String, quantity: Option<f64>, cost_price: Option<f64> }`（`Deserialize`）。
  - `add_portfolio(&self, symbol, type_, market, quantity: Option<f64>, cost: Option<f64>) -> Result<i64>`。
  - `list_portfolio(&self) -> Result<Vec<Holding>>`。
  - `remove_portfolio(&self, id: i64) -> Result<()>`。
  - `report(&self, path: &str) -> Result<Value>`（`/report/today`、`/report/{date}`、`/report/list` 共用 GET）。
  - `trigger(&self) -> Result<String>`（返回 job_id）。
  - `job_status(&self, id: &str) -> Result<Value>`。
  - 内部 `get_json`、`delete` 帮助方法。

- [ ] **Step 1: 写失败测试（追加到 api.rs 的 tests 模块）**

在 `cli/src/api.rs` 的 `mod tests` 内追加：

```rust
    #[test]
    fn add_portfolio_returns_id() {
        let server = MockServer::start();
        server.mock(|when, then| {
            when.method(POST).path("/portfolio");
            then.status(201).json_body(serde_json::json!({"id": 7}));
        });
        let api = Api::new(server.base_url(), Some("tok".into()));
        let id = api.add_portfolio("600519", "stock", "cn", Some(100.0), None).unwrap();
        assert_eq!(id, 7);
    }

    #[test]
    fn list_portfolio_parses_rows() {
        let server = MockServer::start();
        server.mock(|when, then| {
            when.method(GET).path("/portfolio");
            then.status(200).json_body(serde_json::json!([
                {"id": 1, "symbol": "600519", "name": "茅台", "type": "stock",
                 "market": "cn", "quantity": 100.0, "cost_price": null}
            ]));
        });
        let api = Api::new(server.base_url(), Some("tok".into()));
        let rows = api.list_portfolio().unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].symbol, "600519");
        assert_eq!(rows[0].quantity, Some(100.0));
    }

    #[test]
    fn trigger_and_poll() {
        let server = MockServer::start();
        server.mock(|when, then| {
            when.method(POST).path("/trigger-report");
            then.status(202).json_body(serde_json::json!({"job_id": "j1"}));
        });
        server.mock(|when, then| {
            when.method(GET).path("/job/j1");
            then.status(200).json_body(serde_json::json!({"status": "done", "report_date": "2026-06-25"}));
        });
        let api = Api::new(server.base_url(), Some("tok".into()));
        let jid = api.trigger().unwrap();
        assert_eq!(jid, "j1");
        let st = api.job_status(&jid).unwrap();
        assert_eq!(st["status"], "done");
    }
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd cli && cargo test api`
Expected: 编译失败（方法/结构未定义）。

- [ ] **Step 3: 写实现（在 `impl Api` 内追加，并在文件顶部加 `Holding`）**

在 `cli/src/api.rs` 顶部（结构定义区）追加：

```rust
use serde::Deserialize;

#[derive(Deserialize, Debug)]
pub struct Holding {
    pub id: i64,
    pub symbol: String,
    pub name: Option<String>,
    #[serde(rename = "type")]
    pub r#type: String,
    pub market: String,
    pub quantity: Option<f64>,
    pub cost_price: Option<f64>,
}
```

在 `impl Api` 内追加：

```rust
    fn get_json(&self, path: &str) -> Result<Value> {
        let mut req = self.client().get(self.url(path));
        if let Some(t) = &self.token {
            req = req.bearer_auth(t);
        }
        let resp = req.send()?;
        let status = resp.status();
        let text = resp.text().unwrap_or_default();
        if !status.is_success() {
            return Err(anyhow!("HTTP {}: {}", status.as_u16(), text));
        }
        Ok(serde_json::from_str(&text).unwrap_or(Value::Null))
    }

    pub fn add_portfolio(&self, symbol: &str, type_: &str, market: &str,
                         quantity: Option<f64>, cost: Option<f64>) -> Result<i64> {
        let body = json!({
            "symbol": symbol, "type": type_, "market": market,
            "quantity": quantity, "cost_price": cost,
        });
        let v = self.post_json("/portfolio", body)?;
        v["id"].as_i64().ok_or_else(|| anyhow!("no id in response"))
    }

    pub fn list_portfolio(&self) -> Result<Vec<Holding>> {
        let v = self.get_json("/portfolio")?;
        Ok(serde_json::from_value(v)?)
    }

    pub fn remove_portfolio(&self, id: i64) -> Result<()> {
        let mut req = self.client().delete(self.url(&format!("/portfolio/{}", id)));
        if let Some(t) = &self.token {
            req = req.bearer_auth(t);
        }
        let resp = req.send()?;
        if !resp.status().is_success() {
            return Err(anyhow!("HTTP {}", resp.status().as_u16()));
        }
        Ok(())
    }

    pub fn report(&self, path: &str) -> Result<Value> {
        self.get_json(path)
    }

    pub fn trigger(&self) -> Result<String> {
        let v = self.post_json("/trigger-report", json!({}))?;
        v["job_id"].as_str().map(String::from)
            .ok_or_else(|| anyhow!("no job_id"))
    }

    pub fn job_status(&self, id: &str) -> Result<Value> {
        self.get_json(&format!("/job/{}", id))
    }
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd cli && cargo test api`
Expected: PASS（6 passed）。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add cli/src/api.rs
git commit -m "feat(cli): add portfolio/report/trigger api methods"
```

---

## Task 4: CLI 命令接线（clap）

**Files:**
- Create: `cli/src/commands/mod.rs`, `cli/src/commands/auth.rs`, `cli/src/commands/portfolio.rs`, `cli/src/commands/report.rs`, `cli/src/commands/trigger.rs`
- Modify: `cli/src/main.rs`（clap 定义 + 分发）

**Interfaces:**
- Consumes: `config::Config`、`api::Api`。
- Produces: 完整 `pusher` 命令树（见 spec v2 §6.1），各命令返回 `anyhow::Result<()>`。
- 端点解析帮助：`commands::resolve_endpoint(cli_endpoint: Option<String>, cfg: &Config) -> anyhow::Result<String>`。

- [ ] **Step 1: 写端点解析测试**

Create `cli/src/commands/mod.rs`:

```rust
pub mod auth;
pub mod portfolio;
pub mod report;
pub mod trigger;

use crate::config::Config;
use anyhow::{anyhow, Result};

pub fn resolve_endpoint(cli_endpoint: Option<String>, cfg: &Config) -> Result<String> {
    if let Some(e) = cli_endpoint {
        return Ok(e);
    }
    if let Ok(e) = std::env::var("PUSHER_ENDPOINT") {
        if !e.is_empty() {
            return Ok(e);
        }
    }
    if !cfg.server.endpoint.is_empty() {
        return Ok(cfg.server.endpoint.clone());
    }
    Err(anyhow!(
        "no endpoint configured; set PUSHER_ENDPOINT or use --endpoint"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;

    #[test]
    fn prefers_cli_then_config() {
        let mut cfg = Config::default();
        cfg.server.endpoint = "https://cfg".into();
        assert_eq!(resolve_endpoint(Some("https://cli".into()), &cfg).unwrap(), "https://cli");
        std::env::remove_var("PUSHER_ENDPOINT");
        assert_eq!(resolve_endpoint(None, &cfg).unwrap(), "https://cfg");
    }

    #[test]
    fn errors_when_nothing_set() {
        std::env::remove_var("PUSHER_ENDPOINT");
        let cfg = Config::default();
        assert!(resolve_endpoint(None, &cfg).is_err());
    }
}
```

- [ ] **Step 2: 写命令实现**

Create `cli/src/commands/auth.rs`:

```rust
use crate::api::Api;
use crate::config::Config;
use anyhow::Result;

pub fn register(endpoint: String, email: &str) -> Result<()> {
    let pw = rpassword::prompt_password("Password: ")?;
    let token = Api::new(endpoint.clone(), None).register(email, &pw)?;
    save_session(endpoint, email, token)?;
    println!("registered and logged in as {email}");
    Ok(())
}

pub fn login(endpoint: String, email: &str) -> Result<()> {
    let pw = rpassword::prompt_password("Password: ")?;
    let token = Api::new(endpoint.clone(), None).login(email, &pw)?;
    save_session(endpoint, email, token)?;
    println!("logged in as {email}");
    Ok(())
}

pub fn logout() -> Result<()> {
    let mut cfg = Config::load();
    cfg.auth.token.clear();
    cfg.auth.email.clear();
    cfg.save()?;
    println!("logged out");
    Ok(())
}

fn save_session(endpoint: String, email: &str, token: String) -> Result<()> {
    let mut cfg = Config::load();
    cfg.server.endpoint = endpoint;
    cfg.auth.email = email.to_string();
    cfg.auth.token = token;
    cfg.save()
}
```

Create `cli/src/commands/portfolio.rs`:

```rust
use crate::api::Api;
use anyhow::Result;

pub fn add(api: &Api, symbol: &str, type_: &str, market: &str,
           quantity: Option<f64>, cost: Option<f64>) -> Result<()> {
    let id = api.add_portfolio(symbol, type_, market, quantity, cost)?;
    println!("added portfolio #{id}");
    Ok(())
}

pub fn remove(api: &Api, id: i64) -> Result<()> {
    api.remove_portfolio(id)?;
    println!("removed #{id}");
    Ok(())
}

pub fn list(api: &Api) -> Result<()> {
    for h in api.list_portfolio()? {
        let q = h.quantity.map(|v| v.to_string()).unwrap_or_else(|| "-".into());
        println!("#{} {} [{}/{}] qty={}", h.id, h.symbol, h.r#type, h.market, q);
    }
    Ok(())
}
```

Create `cli/src/commands/report.rs`:

```rust
use crate::api::Api;
use anyhow::Result;

pub fn today(api: &Api) -> Result<()> {
    let v = api.report("/report/today")?;
    print_report(&v);
    Ok(())
}

pub fn get(api: &Api, date: &str) -> Result<()> {
    let v = api.report(&format!("/report/{date}"))?;
    print_report(&v);
    Ok(())
}

pub fn list(api: &Api) -> Result<()> {
    let v = api.report("/report/list")?;
    if let Some(dates) = v["dates"].as_array() {
        for d in dates {
            println!("{}", d.as_str().unwrap_or(""));
        }
    }
    Ok(())
}

fn print_report(v: &serde_json::Value) {
    println!("=== {} ===", v["report_date"].as_str().unwrap_or(""));
    println!("{}", v["content"].as_str().unwrap_or(""));
}
```

Create `cli/src/commands/trigger.rs`:

```rust
use crate::api::Api;
use anyhow::Result;
use std::{thread, time::Duration};

pub fn run(api: &Api) -> Result<()> {
    let job_id = api.trigger()?;
    println!("triggered job {job_id}, waiting...");
    loop {
        let st = api.job_status(&job_id)?;
        match st["status"].as_str().unwrap_or("") {
            "done" => {
                println!("done: report {}", st["report_date"].as_str().unwrap_or(""));
                return Ok(());
            }
            "failed" => {
                anyhow::bail!("job failed: {}", st["error"].as_str().unwrap_or(""));
            }
            _ => thread::sleep(Duration::from_secs(3)),
        }
    }
}
```

- [ ] **Step 3: 写 main.rs（clap）**

Edit `cli/src/main.rs`：

```rust
mod api;
mod commands;
mod config;

use anyhow::Result;
use api::Api;
use clap::{Parser, Subcommand};
use commands::resolve_endpoint;
use config::Config;

#[derive(Parser)]
#[command(name = "pusher")]
struct Cli {
    #[arg(long, global = true)]
    endpoint: Option<String>,
    #[command(subcommand)]
    cmd: Command,
}

#[derive(Subcommand)]
enum Command {
    Register { #[arg(long)] email: String },
    Login { #[arg(long)] email: String },
    Logout,
    Portfolio { #[command(subcommand)] action: PortfolioCmd },
    Report { #[command(subcommand)] action: ReportCmd },
    Trigger { #[command(subcommand)] action: TriggerCmd },
}

#[derive(Subcommand)]
enum PortfolioCmd {
    AddStock { code: String,
        #[arg(long, default_value = "cn")] market: String,
        #[arg(long)] quantity: Option<f64>,
        #[arg(long)] cost: Option<f64> },
    AddFund { code: String,
        #[arg(long)] quantity: Option<f64>,
        #[arg(long)] cost: Option<f64> },
    Remove { id: i64 },
    List,
}

#[derive(Subcommand)]
enum ReportCmd {
    Today,
    Get { date: String },
    List,
}

#[derive(Subcommand)]
enum TriggerCmd {
    Run,
}

fn authed_api(cli_endpoint: Option<String>) -> Result<Api> {
    let cfg = Config::load();
    let endpoint = resolve_endpoint(cli_endpoint, &cfg)?;
    let token = if cfg.auth.token.is_empty() { None } else { Some(cfg.auth.token.clone()) };
    Ok(Api::new(endpoint, token))
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.cmd {
        Command::Register { email } => {
            let endpoint = resolve_endpoint(cli.endpoint, &Config::load())?;
            commands::auth::register(endpoint, &email)
        }
        Command::Login { email } => {
            let endpoint = resolve_endpoint(cli.endpoint, &Config::load())?;
            commands::auth::login(endpoint, &email)
        }
        Command::Logout => commands::auth::logout(),
        Command::Portfolio { action } => {
            let api = authed_api(cli.endpoint)?;
            match action {
                PortfolioCmd::AddStock { code, market, quantity, cost } =>
                    commands::portfolio::add(&api, &code, "stock", &market, quantity, cost),
                PortfolioCmd::AddFund { code, quantity, cost } =>
                    commands::portfolio::add(&api, &code, "fund", "cn", quantity, cost),
                PortfolioCmd::Remove { id } => commands::portfolio::remove(&api, id),
                PortfolioCmd::List => commands::portfolio::list(&api),
            }
        }
        Command::Report { action } => {
            let api = authed_api(cli.endpoint)?;
            match action {
                ReportCmd::Today => commands::report::today(&api),
                ReportCmd::Get { date } => commands::report::get(&api, &date),
                ReportCmd::List => commands::report::list(&api),
            }
        }
        Command::Trigger { action } => {
            let api = authed_api(cli.endpoint)?;
            match action {
                TriggerCmd::Run => commands::trigger::run(&api),
            }
        }
    }
}
```

- [ ] **Step 4: 运行测试 + 编译，确认通过**

Run:
```bash
cd cli && cargo test && cargo build
```
Expected: 全部测试 PASS（config 2 + api 6 + commands 2 = 10），`cargo build` 成功产出 `target/debug/pusher`。

- [ ] **Step 5: 烟测命令树（无需真实后端）**

Run: `cd cli && cargo run -- --help`
Expected: 打印含 `register/login/logout/portfolio/report/trigger` 的帮助。

- [ ] **Step 6: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add cli/src/commands/ cli/src/main.rs
git commit -m "feat(cli): wire clap command tree for auth/portfolio/report/trigger"
```

---

## Self-Review

**1. Spec coverage（范围 = spec v2 §6 Rust CLI）：**
- register/login/logout → Task 4 auth + Task 2 api。✅
- portfolio add-stock(--market/--quantity/--cost)/add-fund/remove/list → Task 3/4。✅
- report today/get/list → Task 3/4。✅
- trigger run（触发 + 轮询 job）→ Task 3/4 trigger。✅
- 本地配置 `~/.pusher/config.toml`（server/auth）→ Task 1。✅
- 跨平台编译（§6.3）→ 在子计划 7 部署文档统一给出 4 个 target 的构建命令；CLI 本身无平台特定代码（reqwest 用 rustls，避免 OpenSSL 交叉编译麻烦）。✅

**2. Placeholder 扫描：** 无占位；每命令均有完整实现。✅

**3. 类型一致性：** `Api::new/register/login/add_portfolio/list_portfolio/remove_portfolio/report/trigger/job_status`、`Holding` 字段、`Config`/`config_path`/`load`/`save`、`resolve_endpoint` 在 Interfaces、实现、测试、main 分发间一致；clap 子命令参数与 commands 函数签名一致（`add_portfolio` 的 `type_`/`market`/`quantity`/`cost`）。✅
