# Pusher-Go Advanced — 子计划 1: DB + Schema 基础层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭好 Python 后端骨架，建立 MySQL 全部表结构，并提供一个经测试验证、可在 SCF 复用的数据库连接层。

**Architecture:** Python 包 `server/app`，配置经 `app/config.py` 从环境变量读取；`sql/schema.sql` 定义全部 6 张表；`app/db/mysql.py` 用 PyMySQL 维护一个进程内可复用的连接并提供 `query`/`execute`/`run_script` 帮助函数。测试针对一个真实的本地 MySQL 测试库运行。

**Tech Stack:** Python 3.10+，PyMySQL（纯 Python 驱动，无 C 依赖，便于 SCF 打包），pytest，原生 SQL（不使用 ORM）。

## Global Constraints

- Python 版本：**3.10+**（SCF Python 运行时取 3.10）。
- 数据库驱动：**PyMySQL**，游标统一用 `pymysql.cursors.DictCursor`（查询返回 dict）。
- **不使用 ORM**，全部走原生参数化 SQL（`%s` 占位符），禁止字符串拼接 SQL。
- 所有数据库表、列名按 spec v2 §3 的定义，逐字一致。
- 连接在进程内全局复用（SCF 实例热复用），每次取用前 `ping(reconnect=True)`。
- 包内 import 一律用绝对包路径 `from app.xxx import ...`（在 `server/` 目录下以 `app` 为顶层包）。
- 测试数据库通过环境变量 `MYSQL_*` 指向一个本地 MySQL 测试库；测试不得连生产库。

### 前置：本地测试用 MySQL

执行本计划的测试前，需要一个本地 MySQL。用 Docker 启动一次即可：

```bash
docker run --name pusher-mysql \
  -e MYSQL_ROOT_PASSWORD=root \
  -e MYSQL_DATABASE=pusher_test \
  -p 3306:3306 -d mysql:8.0
```

测试运行时使用的环境变量（写进 shell 或 `.env`，**不要提交**）：

```bash
export MYSQL_HOST=127.0.0.1
export MYSQL_PORT=3306
export MYSQL_USER=root
export MYSQL_PASSWORD=root
export MYSQL_DATABASE=pusher_test
```

---

## File Structure

- `server/requirements.txt` — Python 依赖。
- `server/pytest.ini` — pytest 配置（指定测试根、把 `server/` 加入 import 路径）。
- `server/app/__init__.py` — 包标记。
- `server/app/config.py` — 环境变量配置（`Settings` dataclass + `load_settings()`）。
- `server/app/db/__init__.py` — 包标记。
- `server/app/db/mysql.py` — 连接层（`get_connection`/`query`/`execute`/`run_script`/`reset_connection`）。
- `sql/schema.sql` — 全部建表 DDL。
- `server/tests/__init__.py` — 包标记。
- `server/tests/conftest.py` — pytest fixtures（测试库连接 + 应用 schema）。
- `server/tests/test_config.py` — 配置测试。
- `server/tests/test_schema.py` — schema 建表测试。
- `server/tests/test_mysql.py` — 连接层测试。

---

## Task 1: 项目骨架 + 配置加载

**Files:**
- Create: `server/requirements.txt`
- Create: `server/pytest.ini`
- Create: `server/app/__init__.py`
- Create: `server/app/config.py`
- Create: `server/tests/__init__.py`
- Test: `server/tests/test_config.py`

**Interfaces:**
- Consumes: 无（首个任务）。
- Produces:
  - `app.config.Settings` — dataclass，字段：`mysql_host: str`、`mysql_port: int`、`mysql_user: str`、`mysql_password: str`、`mysql_database: str`、`deepseek_api_key: str`、`deepseek_model: str`、`planner_model: str`、`email_smtp_host: str`、`email_smtp_port: int`、`email_from: str`、`email_password: str`。
  - `app.config.load_settings() -> Settings` — 从 `os.environ` 读取，缺失的非必填项用默认值，必填项缺失抛 `RuntimeError`。

- [ ] **Step 1: 创建依赖与 pytest 配置文件**

Create `server/requirements.txt`:

```
PyMySQL==1.1.1
bcrypt==4.2.0
feedparser==6.0.11
akshare==1.14.81
efinance==0.5.0
yfinance==0.2.43
fastapi==0.115.0
uvicorn==0.30.6
pytest==8.3.3
```

Create `server/pytest.ini`:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

Create `server/app/__init__.py` (空文件):

```python
```

Create `server/tests/__init__.py` (空文件):

```python
```

- [ ] **Step 2: 安装依赖（仅本任务需要的最小集）**

Run:
```bash
cd server && python3 -m pip install PyMySQL==1.1.1 pytest==8.3.3
```
Expected: 安装成功，无报错。（其余重型依赖 akshare/yfinance 等在后续数据层子计划再装。）

- [ ] **Step 3: 写失败测试**

Create `server/tests/test_config.py`:

```python
import os
import pytest
from app.config import Settings, load_settings


def test_load_settings_reads_mysql_env(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "db.example.com")
    monkeypatch.setenv("MYSQL_PORT", "3307")
    monkeypatch.setenv("MYSQL_USER", "alice")
    monkeypatch.setenv("MYSQL_PASSWORD", "secret")
    monkeypatch.setenv("MYSQL_DATABASE", "pusher")

    s = load_settings()

    assert isinstance(s, Settings)
    assert s.mysql_host == "db.example.com"
    assert s.mysql_port == 3307
    assert s.mysql_user == "alice"
    assert s.mysql_password == "secret"
    assert s.mysql_database == "pusher"


def test_load_settings_defaults_for_optional(monkeypatch):
    for key in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
        monkeypatch.setenv(key, "x")
    monkeypatch.delenv("MYSQL_PORT", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    s = load_settings()

    assert s.mysql_port == 3306
    assert s.deepseek_model == "deepseek-chat"
    assert s.planner_model == "deepseek-r1"


def test_load_settings_missing_required_raises(monkeypatch):
    for key in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(RuntimeError):
        load_settings()
```

- [ ] **Step 4: 运行测试，确认失败**

Run:
```bash
cd server && python3 -m pytest tests/test_config.py -v
```
Expected: FAIL，`ModuleNotFoundError: No module named 'app.config'`。

- [ ] **Step 5: 写最小实现**

Create `server/app/config.py`:

```python
import os
from dataclasses import dataclass

_REQUIRED = ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE")


@dataclass
class Settings:
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str
    deepseek_api_key: str
    deepseek_model: str
    planner_model: str
    email_smtp_host: str
    email_smtp_port: int
    email_from: str
    email_password: str


def load_settings() -> Settings:
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"missing required env vars: {', '.join(missing)}")

    return Settings(
        mysql_host=os.environ["MYSQL_HOST"],
        mysql_port=int(os.environ.get("MYSQL_PORT", "3306")),
        mysql_user=os.environ["MYSQL_USER"],
        mysql_password=os.environ["MYSQL_PASSWORD"],
        mysql_database=os.environ["MYSQL_DATABASE"],
        deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        deepseek_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        planner_model=os.environ.get("PLANNER_MODEL", "deepseek-r1"),
        email_smtp_host=os.environ.get("EMAIL_SMTP_HOST", ""),
        email_smtp_port=int(os.environ.get("EMAIL_SMTP_PORT", "587")),
        email_from=os.environ.get("EMAIL_FROM", ""),
        email_password=os.environ.get("EMAIL_PASSWORD", ""),
    )
```

- [ ] **Step 6: 运行测试，确认通过**

Run:
```bash
cd server && python3 -m pytest tests/test_config.py -v
```
Expected: PASS（3 passed）。

- [ ] **Step 7: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/requirements.txt server/pytest.ini server/app/__init__.py server/app/config.py server/tests/__init__.py server/tests/test_config.py
git commit -m "feat(server): scaffold python package and config loader"
```

> 注：若仓库尚未 `git init`，先 `git init` 再提交。

---

## Task 2: schema.sql 全部建表

**Files:**
- Create: `sql/schema.sql`
- Create: `server/app/db/__init__.py`
- Create: `server/tests/conftest.py`
- Test: `server/tests/test_schema.py`

**Interfaces:**
- Consumes: `app.config.load_settings`（Task 1）。
- Produces:
  - `sql/schema.sql` — 含表：`users`、`portfolios`、`fund_holdings`、`reports`、`rss_sources`、`jobs`，全部 `CREATE TABLE IF NOT EXISTS`。
  - conftest fixture `db_conn` — 一个连到测试库、已应用 schema、每个测试函数级别清空数据的 PyMySQL 连接。

- [ ] **Step 1: 写 schema.sql**

Create `sql/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS users (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    email       VARCHAR(255) NOT NULL UNIQUE,
    password    VARCHAR(255) NOT NULL,
    model_key   VARCHAR(255) DEFAULT NULL,
    model_name  VARCHAR(64) DEFAULT NULL,
    model_endpoint VARCHAR(255) DEFAULT NULL,
    email_to    VARCHAR(255) NOT NULL,
    token       VARCHAR(128) NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolios (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    symbol      VARCHAR(32) NOT NULL,
    name        VARCHAR(128),
    type        ENUM('stock', 'fund') NOT NULL,
    market      ENUM('cn', 'hk', 'us') NOT NULL DEFAULT 'cn',
    quantity    DECIMAL(16,4) DEFAULT NULL,
    cost_price  DECIMAL(10,4) DEFAULT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user (user_id)
);

CREATE TABLE IF NOT EXISTS fund_holdings (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    fund_code   VARCHAR(32) NOT NULL,
    stock_code  VARCHAR(32) NOT NULL,
    stock_name  VARCHAR(128),
    ratio       DECIMAL(5,2),
    quarter     VARCHAR(16) NOT NULL,
    updated_at  DATE NOT NULL,
    INDEX idx_fund (fund_code, quarter)
);

CREATE TABLE IF NOT EXISTS reports (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    report_date     DATE NOT NULL,
    content         TEXT,
    news_summary    TEXT,
    stock_summary   TEXT,
    personal_analysis TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user_date (user_id, report_date)
);

CREATE TABLE IF NOT EXISTS rss_sources (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(128),
    url         VARCHAR(512) NOT NULL,
    category    VARCHAR(64),
    lang        VARCHAR(8) DEFAULT 'zh',
    enabled     BOOLEAN DEFAULT TRUE,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id          VARCHAR(36) PRIMARY KEY,
    user_id     INT DEFAULT NULL,
    type        ENUM('pipeline', 'manual_report') NOT NULL,
    status      ENUM('pending', 'running', 'done', 'failed') NOT NULL DEFAULT 'pending',
    error       TEXT DEFAULT NULL,
    report_date DATE DEFAULT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME DEFAULT NULL,
    INDEX idx_user (user_id),
    INDEX idx_status (status)
);
```

- [ ] **Step 2: 创建 db 包标记 + conftest fixture**

Create `server/app/db/__init__.py` (空文件):

```python
```

Create `server/tests/conftest.py`:

```python
import os
import pathlib
import pymysql
import pytest

SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[2] / "sql" / "schema.sql"

# 删除顺序：先删有外键依赖的子表，再删父表
_TABLES_IN_DELETE_ORDER = [
    "reports",
    "portfolios",
    "fund_holdings",
    "rss_sources",
    "jobs",
    "users",
]


def _connect():
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", "root"),
        database=os.environ.get("MYSQL_DATABASE", "pusher_test"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def _apply_schema(conn):
    ddl = SCHEMA_PATH.read_text(encoding="utf-8")
    statements = [s.strip() for s in ddl.split(";") if s.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)


@pytest.fixture
def db_conn():
    conn = _connect()
    _apply_schema(conn)
    # 每个测试开始前清空数据，保证隔离
    with conn.cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        for table in _TABLES_IN_DELETE_ORDER:
            cur.execute(f"DELETE FROM {table}")
        cur.execute("SET FOREIGN_KEY_CHECKS=1")
    yield conn
    conn.close()
```

- [ ] **Step 3: 写失败测试**

Create `server/tests/test_schema.py`:

```python
EXPECTED_TABLES = {
    "users",
    "portfolios",
    "fund_holdings",
    "reports",
    "rss_sources",
    "jobs",
}


def test_all_tables_created(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        rows = cur.fetchall()
    # DictCursor 下每行是 {'Tables_in_<db>': name}
    names = {list(r.values())[0] for r in rows}
    assert EXPECTED_TABLES.issubset(names)


def test_portfolios_has_market_column(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM portfolios LIKE 'market'")
        col = cur.fetchone()
    assert col is not None
    assert "enum('cn','hk','us')" in col["Type"].lower()


def test_portfolios_quantity_nullable(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM portfolios LIKE 'quantity'")
        col = cur.fetchone()
    assert col is not None
    assert col["Null"] == "YES"


def test_jobs_status_default_pending(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM jobs LIKE 'status'")
        col = cur.fetchone()
    assert col is not None
    assert col["Default"] == "pending"
```

- [ ] **Step 4: 运行测试，确认通过**

Run:
```bash
cd server && python3 -m pytest tests/test_schema.py -v
```
Expected: PASS（4 passed）。前提是本地 MySQL 测试库已按"前置"启动并设置好环境变量。

> 说明：本任务无独立"失败再实现"循环，因为 schema 即实现、测试即验证。若测试因连不上库失败，先检查 Docker 容器与 `MYSQL_*` 环境变量。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add sql/schema.sql server/app/db/__init__.py server/tests/conftest.py server/tests/test_schema.py
git commit -m "feat(db): add full mysql schema and test fixtures"
```

---

## Task 3: 数据库连接层

**Files:**
- Create: `server/app/db/mysql.py`
- Test: `server/tests/test_mysql.py`

**Interfaces:**
- Consumes: `app.config.load_settings`（Task 1）；`sql/schema.sql`（Task 2）。
- Produces:
  - `app.db.mysql.get_connection() -> pymysql.connections.Connection` — 返回进程内复用的连接，取用前 `ping(reconnect=True)`。
  - `app.db.mysql.query(sql: str, params: tuple | None = None) -> list[dict]` — 查询，返回行列表（dict）。
  - `app.db.mysql.execute(sql: str, params: tuple | None = None) -> int` — 写操作，提交后返回 `lastrowid`。
  - `app.db.mysql.run_script(sql_text: str) -> None` — 执行多语句 DDL 脚本（按 `;` 切分）。
  - `app.db.mysql.reset_connection() -> None` — 关闭并清空全局连接（测试隔离用）。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_mysql.py`:

```python
import pytest
from app.db import mysql


@pytest.fixture(autouse=True)
def _reset_global_conn():
    # 每个测试前后重置全局连接，避免跨测试串连
    mysql.reset_connection()
    yield
    mysql.reset_connection()


def test_get_connection_is_reused():
    c1 = mysql.get_connection()
    c2 = mysql.get_connection()
    assert c1 is c2


def test_execute_and_query_roundtrip(db_conn):
    new_id = mysql.execute(
        "INSERT INTO users (email, password, email_to, token) "
        "VALUES (%s, %s, %s, %s)",
        ("a@b.com", "hashed", "a@b.com", "tok123"),
    )
    assert isinstance(new_id, int) and new_id > 0

    rows = mysql.query("SELECT email, token FROM users WHERE id = %s", (new_id,))
    assert rows == [{"email": "a@b.com", "token": "tok123"}]


def test_query_returns_empty_list_when_no_rows(db_conn):
    rows = mysql.query("SELECT id FROM users WHERE email = %s", ("nope@x.com",))
    assert rows == []


def test_run_script_executes_multiple_statements(db_conn):
    mysql.run_script(
        "INSERT INTO rss_sources (name, url) VALUES ('s1', 'http://1');"
        "INSERT INTO rss_sources (name, url) VALUES ('s2', 'http://2');"
    )
    rows = mysql.query("SELECT name FROM rss_sources ORDER BY name")
    assert [r["name"] for r in rows] == ["s1", "s2"]
```

> 注：`db_conn` fixture（来自 conftest）负责应用 schema 并清空数据；连接层用自己的全局连接但连同一个测试库，因此能看到同一份表结构。

- [ ] **Step 2: 运行测试，确认失败**

Run:
```bash
cd server && python3 -m pytest tests/test_mysql.py -v
```
Expected: FAIL，`ModuleNotFoundError` 或 `AttributeError: module 'app.db.mysql' has no attribute ...`。

- [ ] **Step 3: 写实现**

Create `server/app/db/mysql.py`:

```python
import pymysql
from app.config import load_settings

_conn = None


def get_connection():
    global _conn
    if _conn is None or not _conn.open:
        s = load_settings()
        _conn = pymysql.connect(
            host=s.mysql_host,
            port=s.mysql_port,
            user=s.mysql_user,
            password=s.mysql_password,
            database=s.mysql_database,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
    _conn.ping(reconnect=True)
    return _conn


def query(sql, params=None):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())


def execute(sql, params=None):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        conn.commit()
        return cur.lastrowid


def run_script(sql_text):
    conn = get_connection()
    statements = [s.strip() for s in sql_text.split(";") if s.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
    conn.commit()


def reset_connection():
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _conn = None
```

- [ ] **Step 4: 运行测试，确认通过**

Run:
```bash
cd server && python3 -m pytest tests/test_mysql.py -v
```
Expected: PASS（4 passed）。

- [ ] **Step 5: 运行全部测试，确认整体绿**

Run:
```bash
cd server && python3 -m pytest -v
```
Expected: PASS（test_config 3 + test_schema 4 + test_mysql 4 = 11 passed）。

- [ ] **Step 6: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/db/mysql.py server/tests/test_mysql.py
git commit -m "feat(db): add reusable pymysql connection layer with helpers"
```

---

## Self-Review

**1. Spec coverage（本子计划范围 = spec v2 §3 全部表 + §8 db 层 + §2.2 技术选型）：**
- §3.1–§3.6 六张表 → Task 2 schema.sql 全覆盖（含 v2 新增的 `portfolios.market`、`jobs` 表）。✅
- §8 `server/app/db/mysql.py`、`server/app/config.py` → Task 1/3。✅
- §7.1 连接复用/上限 → `get_connection` 进程内复用 + `ping(reconnect=True)`；连接池上限策略留待部署子计划（个位数用户单连接足够）。✅
- 各表 CRUD/模型 → 有意延后到对应 API 子计划，本计划只交付 schema + 通用连接层。✅（范围说明已在顶部声明）

**2. Placeholder 扫描：** 无 TBD/TODO/"appropriate error handling" 等占位；每个代码步骤都给了完整代码。✅

**3. 类型一致性：** `get_connection`/`query`/`execute`/`run_script`/`reset_connection` 在 Interfaces、实现、测试三处签名一致；`Settings` 字段在 config 实现与 test_config 断言一致；表名/列名在 schema.sql、conftest、测试断言间一致（`market` ENUM、`jobs.status` 默认 `pending`、`quantity` 可空）。✅
