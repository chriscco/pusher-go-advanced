# Pusher-Go Advanced — 子计划 2: Auth + Portfolio API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现用户注册/登录（bcrypt + 长期 token）与持仓 CRUD 的 FastAPI 接口，并提供 Bearer token 鉴权依赖。

**Architecture:** `app/main.py` 创建 FastAPI 应用并挂载路由；`app/auth/security.py` 提供密码哈希与 token 生成；`app/models/user.py`、`app/models/portfolio.py` 封装原生 SQL CRUD；`app/deps.py` 提供 `get_current_user` 鉴权依赖；`app/api/auth.py`、`app/api/portfolio.py` 定义端点。测试用 FastAPI `TestClient` 对真实测试库跑端到端。

**Tech Stack:** FastAPI、Starlette TestClient（依赖 httpx）、bcrypt、PyMySQL（经子计划 1 的 `app.db.mysql`）。

## Global Constraints

- 继承子计划 1 的全部约束（Python 3.10+、PyMySQL DictCursor、原生参数化 SQL、`from app.xxx import`、测试针对本地 MySQL 测试库）。
- 密码用 **bcrypt** 哈希，绝不明文存储或返回。
- token 为 **128 字符** URL-safe 随机串（`secrets.token_urlsafe` 取够长度后截断到 128）。
- 鉴权头格式：`Authorization: Bearer <token>`，缺失/非法一律返回 **401**。
- 所有需要鉴权的端点经 `Depends(get_current_user)`；越权操作（删别人持仓）返回 **404**（不泄露存在性）。
- 表/列名严格对齐子计划 1 的 `sql/schema.sql`。

### 前置
本子计划测试同样需要子计划 1 的本地 MySQL 测试库与 `MYSQL_*` 环境变量。`db_conn` fixture（来自 `server/tests/conftest.py`）负责应用 schema 并清表。

---

## File Structure

- `server/app/auth/__init__.py` — 包标记。
- `server/app/auth/security.py` — `hash_password`/`verify_password`/`generate_token`。
- `server/app/models/__init__.py` — 包标记。
- `server/app/models/user.py` — 用户 CRUD。
- `server/app/models/portfolio.py` — 持仓 CRUD。
- `server/app/deps.py` — `get_current_user` 鉴权依赖。
- `server/app/api/__init__.py` — 包标记。
- `server/app/api/auth.py` — `/register`、`/login` 路由。
- `server/app/api/portfolio.py` — `/portfolio` 路由。
- `server/app/main.py` — FastAPI app，挂载路由。
- `server/tests/test_security.py`、`test_user_model.py`、`test_portfolio_model.py`、`test_auth_api.py`、`test_portfolio_api.py` — 测试。

---

## Task 1: 密码与 token 安全工具

**Files:**
- Create: `server/app/auth/__init__.py`, `server/app/auth/security.py`
- Test: `server/tests/test_security.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `app.auth.security.hash_password(plain: str) -> str` — bcrypt 哈希（返回 utf-8 字符串）。
  - `app.auth.security.verify_password(plain: str, hashed: str) -> bool`。
  - `app.auth.security.generate_token() -> str` — 128 字符随机串。

- [ ] **Step 1: 安装本任务依赖**

Run:
```bash
cd server && python3 -m pip install bcrypt==4.2.0 httpx
```
Expected: 安装成功（httpx 供后续 TestClient 用）。

- [ ] **Step 2: 写失败测试**

Create `server/tests/test_security.py`:

```python
from app.auth.security import hash_password, verify_password, generate_token


def test_hash_password_is_not_plaintext():
    h = hash_password("hunter2")
    assert h != "hunter2"
    assert isinstance(h, str)


def test_verify_password_roundtrip():
    h = hash_password("hunter2")
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False


def test_generate_token_length_and_uniqueness():
    t1 = generate_token()
    t2 = generate_token()
    assert len(t1) == 128
    assert t1 != t2
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_security.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.auth'`。

- [ ] **Step 4: 写实现**

Create `server/app/auth/__init__.py` (空文件):

```python
```

Create `server/app/auth/security.py`:

```python
import secrets
import bcrypt


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def generate_token() -> str:
    # token_urlsafe(96) 约 128 字符，截断到精确 128
    return secrets.token_urlsafe(128)[:128]
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_security.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 6: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/auth/ server/tests/test_security.py
git commit -m "feat(auth): add bcrypt password hashing and token generation"
```

---

## Task 2: 用户模型 CRUD

**Files:**
- Create: `server/app/models/__init__.py`, `server/app/models/user.py`
- Test: `server/tests/test_user_model.py`

**Interfaces:**
- Consumes: `app.db.mysql.execute/query`（子计划 1）。
- Produces:
  - `app.models.user.create_user(email, password_hash, email_to, token) -> int`（返回新用户 id）。
  - `app.models.user.get_user_by_email(email) -> dict | None`。
  - `app.models.user.get_user_by_token(token) -> dict | None`。
  - `app.models.user.set_user_token(user_id, token) -> None`。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_user_model.py`:

```python
import pytest
from app.db import mysql
from app.models import user


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


def test_create_and_get_by_email():
    uid = user.create_user("u@x.com", "hash1", "u@x.com", "tok1")
    assert isinstance(uid, int) and uid > 0

    row = user.get_user_by_email("u@x.com")
    assert row["id"] == uid
    assert row["password"] == "hash1"
    assert row["token"] == "tok1"


def test_get_by_email_missing_returns_none():
    assert user.get_user_by_email("nobody@x.com") is None


def test_get_by_token():
    uid = user.create_user("t@x.com", "h", "t@x.com", "tokABC")
    row = user.get_user_by_token("tokABC")
    assert row["id"] == uid
    assert user.get_user_by_token("nope") is None


def test_set_user_token():
    uid = user.create_user("s@x.com", "h", "s@x.com", "old")
    user.set_user_token(uid, "new")
    assert user.get_user_by_token("old") is None
    assert user.get_user_by_token("new")["id"] == uid
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_user_model.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.models'`。

- [ ] **Step 3: 写实现**

Create `server/app/models/__init__.py` (空文件):

```python
```

Create `server/app/models/user.py`:

```python
from app.db import mysql


def create_user(email, password_hash, email_to, token) -> int:
    return mysql.execute(
        "INSERT INTO users (email, password, email_to, token) "
        "VALUES (%s, %s, %s, %s)",
        (email, password_hash, email_to, token),
    )


def get_user_by_email(email):
    rows = mysql.query("SELECT * FROM users WHERE email = %s", (email,))
    return rows[0] if rows else None


def get_user_by_token(token):
    rows = mysql.query("SELECT * FROM users WHERE token = %s", (token,))
    return rows[0] if rows else None


def set_user_token(user_id, token) -> None:
    mysql.execute("UPDATE users SET token = %s WHERE id = %s", (token, user_id))
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_user_model.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/models/__init__.py server/app/models/user.py server/tests/test_user_model.py
git commit -m "feat(models): add user crud"
```

---

## Task 3: 持仓模型 CRUD

**Files:**
- Create: `server/app/models/portfolio.py`
- Test: `server/tests/test_portfolio_model.py`

**Interfaces:**
- Consumes: `app.db.mysql`、`app.models.user.create_user`（建测试用户）。
- Produces:
  - `app.models.portfolio.add_portfolio(user_id, symbol, name, type_, market, quantity, cost_price) -> int`。
  - `app.models.portfolio.list_portfolios(user_id) -> list[dict]`。
  - `app.models.portfolio.get_portfolio(portfolio_id) -> dict | None`。
  - `app.models.portfolio.delete_portfolio(portfolio_id, user_id) -> bool`（仅本人；删成功 True，无匹配 False）。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_portfolio_model.py`:

```python
import pytest
from app.db import mysql
from app.models import user, portfolio


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


@pytest.fixture
def uid():
    return user.create_user("p@x.com", "h", "p@x.com", "tok")


def test_add_and_list(uid):
    pid = portfolio.add_portfolio(uid, "600519", "贵州茅台", "stock", "cn", 100, 1500.0)
    assert isinstance(pid, int) and pid > 0

    rows = portfolio.list_portfolios(uid)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "600519"
    assert rows[0]["market"] == "cn"
    assert float(rows[0]["quantity"]) == 100.0


def test_add_optional_fields_null(uid):
    pid = portfolio.add_portfolio(uid, "AAPL", None, "stock", "us", None, None)
    row = portfolio.get_portfolio(pid)
    assert row["quantity"] is None
    assert row["cost_price"] is None
    assert row["market"] == "us"


def test_delete_own(uid):
    pid = portfolio.add_portfolio(uid, "600519", None, "stock", "cn", None, None)
    assert portfolio.delete_portfolio(pid, uid) is True
    assert portfolio.get_portfolio(pid) is None


def test_delete_other_users_fails(uid):
    other = user.create_user("o@x.com", "h", "o@x.com", "tok2")
    pid = portfolio.add_portfolio(uid, "600519", None, "stock", "cn", None, None)
    assert portfolio.delete_portfolio(pid, other) is False
    assert portfolio.get_portfolio(pid) is not None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_portfolio_model.py -v`
Expected: FAIL，`ImportError: cannot import name 'portfolio'`。

- [ ] **Step 3: 写实现**

Create `server/app/models/portfolio.py`:

```python
from app.db import mysql


def add_portfolio(user_id, symbol, name, type_, market, quantity, cost_price) -> int:
    return mysql.execute(
        "INSERT INTO portfolios "
        "(user_id, symbol, name, type, market, quantity, cost_price) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (user_id, symbol, name, type_, market, quantity, cost_price),
    )


def list_portfolios(user_id):
    return mysql.query(
        "SELECT * FROM portfolios WHERE user_id = %s ORDER BY id", (user_id,)
    )


def get_portfolio(portfolio_id):
    rows = mysql.query("SELECT * FROM portfolios WHERE id = %s", (portfolio_id,))
    return rows[0] if rows else None


def delete_portfolio(portfolio_id, user_id) -> bool:
    affected = mysql.execute(
        "DELETE FROM portfolios WHERE id = %s AND user_id = %s",
        (portfolio_id, user_id),
    )
    # execute 返回 lastrowid，对 DELETE 无意义；改用 rowcount 判断
    return _last_rowcount() > 0


def _last_rowcount() -> int:
    conn = mysql.get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT ROW_COUNT() AS n")
        return int(cur.fetchone()["n"])
```

> 注：`mysql.execute` 返回 `lastrowid`（对 DELETE 无意义），故用 `ROW_COUNT()` 取受影响行数判断删除是否命中。`ROW_COUNT()` 返回上一条 DML 的影响行数，需在同一连接、紧随 DELETE 之后调用——上面 `delete_portfolio` 已保证顺序。

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_portfolio_model.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/models/portfolio.py server/tests/test_portfolio_model.py
git commit -m "feat(models): add portfolio crud with ownership-scoped delete"
```

---

## Task 4: FastAPI 应用 + 鉴权依赖 + Auth 端点

**Files:**
- Create: `server/app/deps.py`, `server/app/api/__init__.py`, `server/app/api/auth.py`, `server/app/main.py`
- Test: `server/tests/test_auth_api.py`

**Interfaces:**
- Consumes: `app.auth.security`、`app.models.user`。
- Produces:
  - `app.deps.get_current_user(authorization: str = Header(None)) -> dict`（FastAPI 依赖；失败抛 401）。
  - `app.main.app` — FastAPI 实例，已挂载 auth 路由。
  - 端点 `POST /register`：body `{email, password, email_to?}` → `{token}`（201）；email 重复 → 409。
  - 端点 `POST /login`：body `{email, password}` → `{token}`（200，每次登录重置 token）；失败 → 401。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_auth_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from app.db import mysql
from app.main import app


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


@pytest.fixture
def client():
    return TestClient(app)


def test_register_returns_token(client):
    r = client.post("/register", json={"email": "a@x.com", "password": "pw"})
    assert r.status_code == 201
    assert len(r.json()["token"]) == 128


def test_register_duplicate_email_conflicts(client):
    client.post("/register", json={"email": "a@x.com", "password": "pw"})
    r = client.post("/register", json={"email": "a@x.com", "password": "pw"})
    assert r.status_code == 409


def test_login_success_returns_new_token(client):
    reg = client.post("/register", json={"email": "a@x.com", "password": "pw"})
    old = reg.json()["token"]
    r = client.post("/login", json={"email": "a@x.com", "password": "pw"})
    assert r.status_code == 200
    new = r.json()["token"]
    assert len(new) == 128
    assert new != old  # 登录重置 token


def test_login_wrong_password_401(client):
    client.post("/register", json={"email": "a@x.com", "password": "pw"})
    r = client.post("/login", json={"email": "a@x.com", "password": "BAD"})
    assert r.status_code == 401
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_auth_api.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.main'`。

- [ ] **Step 3: 写鉴权依赖**

Create `server/app/deps.py`:

```python
from fastapi import Header, HTTPException
from app.models import user as user_model


def get_current_user(authorization: str = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[len("Bearer "):]
    u = user_model.get_user_by_token(token)
    if not u:
        raise HTTPException(status_code=401, detail="invalid token")
    return u
```

- [ ] **Step 4: 写 auth 路由**

Create `server/app/api/__init__.py` (空文件):

```python
```

Create `server/app/api/auth.py`:

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from app.auth.security import hash_password, verify_password, generate_token
from app.models import user as user_model

router = APIRouter()


class RegisterBody(BaseModel):
    email: EmailStr
    password: str
    email_to: EmailStr | None = None


class LoginBody(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=201)
def register(body: RegisterBody):
    if user_model.get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="email already registered")
    token = generate_token()
    email_to = body.email_to or body.email
    user_model.create_user(
        body.email, hash_password(body.password), email_to, token
    )
    return {"token": token}


@router.post("/login")
def login(body: LoginBody):
    u = user_model.get_user_by_email(body.email)
    if not u or not verify_password(body.password, u["password"]):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = generate_token()
    user_model.set_user_token(u["id"], token)
    return {"token": token}
```

- [ ] **Step 5: 写 main app**

Create `server/app/main.py`:

```python
from fastapi import FastAPI
from app.api import auth

app = FastAPI(title="pusher-go-advanced")
app.include_router(auth.router)
```

- [ ] **Step 6: 安装 email 校验依赖并运行测试**

Run:
```bash
cd server && python3 -m pip install "pydantic[email]"
python3 -m pytest tests/test_auth_api.py -v
```
Expected: PASS（4 passed）。

> 提示：`EmailStr` 需要 `email-validator`，由 `pydantic[email]` 带入。把 `pydantic[email]` 加进 `requirements.txt`（在 fastapi 行后追加一行 `email-validator==2.2.0`）。

- [ ] **Step 7: 把 email-validator 写进 requirements**

Edit `server/requirements.txt`，在 `uvicorn` 行后新增一行：

```
email-validator==2.2.0
httpx==0.27.2
```

- [ ] **Step 8: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/deps.py server/app/api/__init__.py server/app/api/auth.py server/app/main.py server/requirements.txt server/tests/test_auth_api.py
git commit -m "feat(api): add fastapi app, auth deps, register/login endpoints"
```

---

## Task 5: Portfolio 端点

**Files:**
- Create: `server/app/api/portfolio.py`
- Modify: `server/app/main.py`（挂载 portfolio 路由）
- Test: `server/tests/test_portfolio_api.py`

**Interfaces:**
- Consumes: `app.deps.get_current_user`、`app.models.portfolio`。
- Produces：
  - `POST /portfolio`：body `{symbol, type, market?, name?, quantity?, cost_price?}` → `{id}`（201）。
  - `GET /portfolio` → `[{id, symbol, name, type, market, quantity, cost_price}, ...]`。
  - `DELETE /portfolio/{pid}` → 204；非本人/不存在 → 404。
  - 全部需 Bearer，缺 token → 401。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_portfolio_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from app.db import mysql
from app.main import app


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


@pytest.fixture
def client():
    return TestClient(app)


def _auth(client, email="a@x.com"):
    token = client.post(
        "/register", json={"email": email, "password": "pw"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_requires_auth(client):
    assert client.get("/portfolio").status_code == 401


def test_add_list_delete(client):
    h = _auth(client)
    r = client.post(
        "/portfolio",
        json={"symbol": "600519", "type": "stock", "market": "cn", "quantity": 100},
        headers=h,
    )
    assert r.status_code == 201
    pid = r.json()["id"]

    lst = client.get("/portfolio", headers=h).json()
    assert len(lst) == 1
    assert lst[0]["symbol"] == "600519"

    assert client.delete(f"/portfolio/{pid}", headers=h).status_code == 204
    assert client.get("/portfolio", headers=h).json() == []


def test_default_market_is_cn(client):
    h = _auth(client)
    r = client.post("/portfolio", json={"symbol": "000001", "type": "stock"}, headers=h)
    pid = r.json()["id"]
    row = client.get("/portfolio", headers=h).json()[0]
    assert row["market"] == "cn"


def test_cannot_delete_others(client):
    h1 = _auth(client, "one@x.com")
    h2 = _auth(client, "two@x.com")
    pid = client.post(
        "/portfolio", json={"symbol": "600519", "type": "stock"}, headers=h1
    ).json()["id"]
    assert client.delete(f"/portfolio/{pid}", headers=h2).status_code == 404
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_portfolio_api.py -v`
Expected: FAIL（401 处通过，但 add/list 404，因为路由未挂载）。

- [ ] **Step 3: 写 portfolio 路由**

Create `server/app/api/portfolio.py`:

```python
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from app.deps import get_current_user
from app.models import portfolio as pf

router = APIRouter()


class AddBody(BaseModel):
    symbol: str
    type: Literal["stock", "fund"]
    market: Literal["cn", "hk", "us"] = "cn"
    name: str | None = None
    quantity: float | None = None
    cost_price: float | None = None


@router.post("/portfolio", status_code=201)
def add(body: AddBody, user=Depends(get_current_user)):
    pid = pf.add_portfolio(
        user["id"], body.symbol, body.name, body.type,
        body.market, body.quantity, body.cost_price,
    )
    return {"id": pid}


@router.get("/portfolio")
def list_(user=Depends(get_current_user)):
    rows = pf.list_portfolios(user["id"])
    return [
        {
            "id": r["id"],
            "symbol": r["symbol"],
            "name": r["name"],
            "type": r["type"],
            "market": r["market"],
            "quantity": float(r["quantity"]) if r["quantity"] is not None else None,
            "cost_price": float(r["cost_price"]) if r["cost_price"] is not None else None,
        }
        for r in rows
    ]


@router.delete("/portfolio/{pid}", status_code=204)
def delete(pid: int, user=Depends(get_current_user)):
    if not pf.delete_portfolio(pid, user["id"]):
        raise HTTPException(status_code=404, detail="portfolio not found")
    return Response(status_code=204)
```

- [ ] **Step 4: 挂载路由**

Edit `server/app/main.py`，改为：

```python
from fastapi import FastAPI
from app.api import auth, portfolio

app = FastAPI(title="pusher-go-advanced")
app.include_router(auth.router)
app.include_router(portfolio.router)
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_portfolio_api.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 6: 运行全部测试**

Run: `cd server && python3 -m pytest -v`
Expected: 全绿（子计划 1 的 11 + 本计划新增全部通过）。

- [ ] **Step 7: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/api/portfolio.py server/app/main.py server/tests/test_portfolio_api.py
git commit -m "feat(api): add portfolio crud endpoints with ownership checks"
```

---

## Self-Review

**1. Spec coverage（范围 = spec v2 §5.1 的 register/login/portfolio 三类 + §9 安全）：**
- POST /register、/login → Task 4。✅（login 重置 token，符合 §3.1 单一长期 token 语义）
- POST/GET/DELETE /portfolio（含 market/quantity/cost 可选）→ Task 5。✅
- bcrypt 密码、128 字符 token → Task 1。✅
- Bearer 鉴权、越权 404 → Task 4/5。✅
- report/trigger/job 端点 → 不在本计划范围（子计划 4/5）。✅

**2. Placeholder 扫描：** 无占位；每步含完整代码与预期输出。✅

**3. 类型一致性：** `create_user/get_user_by_email/get_user_by_token/set_user_token`、`add_portfolio/list_portfolios/get_portfolio/delete_portfolio`、`get_current_user`、`app.main.app` 在 Interfaces、实现、测试三处签名一致；端点字段与 pydantic 模型一致；`delete_portfolio` 的 `(portfolio_id, user_id) -> bool` 在 model 与 api 调用一致。✅
