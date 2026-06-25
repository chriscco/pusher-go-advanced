# Pusher-Go Advanced — 子计划 4: 报告持久化 + 报告 API + 邮件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供报告的持久化与查询（今日/指定日期/历史列表）接口，以及把 HTML 报告推送到用户邮箱的发信能力——这些是流水线（子计划 5）跑通"存一份报告 + 发邮件"的前置。

**Architecture:** `app/models/report.py` 封装报告读写；`app/api/report.py` 暴露查询端点（复用子计划 2 的鉴权依赖）；`app/pipeline/email.py` 用标准库 `smtplib` 发信，SMTP 客户端可注入以便测试。

**Tech Stack:** PyMySQL（经 `app.db.mysql`）、FastAPI、Python 标准库 `smtplib`/`email`。

## Global Constraints

- 继承子计划 1/2 的约束（含 `db_conn` fixture、`get_current_user` 鉴权、`app.main.app`）。
- 日期统一用 `Asia/Shanghai`；API 路径中的日期格式为 `YYYY-MM-DD`，非法格式返回 **400**。
- 报告查询端点需 Bearer 鉴权，只能查本人报告。
- 发信失败必须抛出可识别异常（供流水线标记 job 失败/记录），不得静默吞掉。
- 严格使用子计划 1 的 `reports` 表列名。

### 前置
依赖子计划 1（`app.db.mysql`、schema）、子计划 2（`app.deps.get_current_user`、`app.main.app`、`app.models.user`）。测试用本地 MySQL 测试库。

---

## File Structure

- `server/app/models/report.py` — 报告读写。
- `server/app/api/report.py` — 报告查询端点。
- `server/app/pipeline/__init__.py` — 包标记。
- `server/app/pipeline/email.py` — 邮件发送。
- `server/tests/test_report_model.py`、`test_report_api.py`、`test_email.py` — 测试。

---

## Task 1: 报告模型读写

**Files:**
- Create: `server/app/models/report.py`
- Test: `server/tests/test_report_model.py`

**Interfaces:**
- Consumes: `app.db.mysql`、`app.models.user.create_user`。
- Produces:
  - `app.models.report.save_report(user_id, report_date, content, news_summary, stock_summary, personal_analysis) -> int`。
  - `app.models.report.get_report(user_id, report_date) -> dict | None`（`report_date` 为 `datetime.date` 或 `YYYY-MM-DD` 字符串）。
  - `app.models.report.get_today_report(user_id) -> dict | None`（北京今天）。
  - `app.models.report.list_report_dates(user_id) -> list[str]`（降序的 `YYYY-MM-DD` 列表）。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_report_model.py`:

```python
import datetime
import pytest
from app.db import mysql
from app.models import user, report


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


@pytest.fixture
def uid():
    return user.create_user("r@x.com", "h", "r@x.com", "tok")


def test_save_and_get(uid):
    rid = report.save_report(uid, "2026-06-24", "<h1>r</h1>", "news", "stock", "me")
    assert isinstance(rid, int) and rid > 0
    row = report.get_report(uid, "2026-06-24")
    assert row["content"] == "<h1>r</h1>"
    assert row["news_summary"] == "news"


def test_get_missing_returns_none(uid):
    assert report.get_report(uid, "2099-01-01") is None


def test_get_today(uid, monkeypatch):
    today = datetime.date(2026, 6, 25)
    monkeypatch.setattr(report, "beijing_today", lambda: today)
    report.save_report(uid, today, "<p>today</p>", "n", "s", "p")
    row = report.get_today_report(uid)
    assert row["content"] == "<p>today</p>"


def test_list_dates_descending(uid):
    report.save_report(uid, "2026-06-22", "a", "n", "s", "p")
    report.save_report(uid, "2026-06-24", "b", "n", "s", "p")
    report.save_report(uid, "2026-06-23", "c", "n", "s", "p")
    assert report.list_report_dates(uid) == ["2026-06-24", "2026-06-23", "2026-06-22"]
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_report_model.py -v`
Expected: FAIL，`ImportError: cannot import name 'report'`。

- [ ] **Step 3: 写实现**

Create `server/app/models/report.py`:

```python
from datetime import datetime, timezone, timedelta
from app.db import mysql

_BEIJING = timezone(timedelta(hours=8))


def beijing_today():
    return datetime.now(_BEIJING).date()


def save_report(user_id, report_date, content, news_summary,
                stock_summary, personal_analysis) -> int:
    return mysql.execute(
        "INSERT INTO reports "
        "(user_id, report_date, content, news_summary, stock_summary, personal_analysis) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (user_id, report_date, content, news_summary, stock_summary, personal_analysis),
    )


def get_report(user_id, report_date):
    rows = mysql.query(
        "SELECT * FROM reports WHERE user_id = %s AND report_date = %s "
        "ORDER BY id DESC LIMIT 1",
        (user_id, report_date),
    )
    return rows[0] if rows else None


def get_today_report(user_id):
    return get_report(user_id, beijing_today())


def list_report_dates(user_id) -> list[str]:
    rows = mysql.query(
        "SELECT DISTINCT report_date FROM reports WHERE user_id = %s "
        "ORDER BY report_date DESC",
        (user_id,),
    )
    return [r["report_date"].strftime("%Y-%m-%d") for r in rows]
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_report_model.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/models/report.py server/tests/test_report_model.py
git commit -m "feat(models): add report persistence and queries"
```

---

## Task 2: 报告查询端点

**Files:**
- Create: `server/app/api/report.py`
- Modify: `server/app/main.py`（挂载 report 路由）
- Test: `server/tests/test_report_api.py`

**Interfaces:**
- Consumes: `app.deps.get_current_user`、`app.models.report`。
- Produces:
  - `GET /report/today` → `{report_date, content, news_summary, stock_summary, personal_analysis}`；无则 404。
  - `GET /report/{date}` → 同上；`date` 非 `YYYY-MM-DD` → 400；无则 404。
  - `GET /report/list` → `{dates: [...]}`。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_report_api.py`:

```python
import datetime
import pytest
from fastapi.testclient import TestClient
from app.db import mysql
from app.main import app
from app.models import user, report


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


@pytest.fixture
def client():
    return TestClient(app)


def _auth(client):
    token = client.post(
        "/register", json={"email": "a@x.com", "password": "pw"}
    ).json()["token"]
    return token, {"Authorization": f"Bearer {token}"}


def test_report_list(client):
    token, h = _auth(client)
    uid = user.get_user_by_token(token)["id"]
    report.save_report(uid, "2026-06-24", "c", "n", "s", "p")
    r = client.get("/report/list", headers=h)
    assert r.status_code == 200
    assert r.json()["dates"] == ["2026-06-24"]


def test_report_by_date(client):
    token, h = _auth(client)
    uid = user.get_user_by_token(token)["id"]
    report.save_report(uid, "2026-06-24", "<b>x</b>", "n", "s", "p")
    r = client.get("/report/2026-06-24", headers=h)
    assert r.status_code == 200
    assert r.json()["content"] == "<b>x</b>"


def test_report_by_date_bad_format(client):
    _, h = _auth(client)
    assert client.get("/report/not-a-date", headers=h).status_code == 400


def test_report_missing_404(client):
    _, h = _auth(client)
    assert client.get("/report/2099-01-01", headers=h).status_code == 404


def test_report_today(client, monkeypatch):
    token, h = _auth(client)
    uid = user.get_user_by_token(token)["id"]
    monkeypatch.setattr(report, "beijing_today", lambda: datetime.date(2026, 6, 25))
    report.save_report(uid, datetime.date(2026, 6, 25), "today", "n", "s", "p")
    r = client.get("/report/today", headers=h)
    assert r.status_code == 200 and r.json()["content"] == "today"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_report_api.py -v`
Expected: FAIL（路由未挂载，404/AttributeError）。

- [ ] **Step 3: 写 report 路由**

Create `server/app/api/report.py`:

```python
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from app.deps import get_current_user
from app.models import report as report_model

router = APIRouter()


def _serialize(row):
    rd = row["report_date"]
    return {
        "report_date": rd.strftime("%Y-%m-%d") if hasattr(rd, "strftime") else str(rd),
        "content": row["content"],
        "news_summary": row["news_summary"],
        "stock_summary": row["stock_summary"],
        "personal_analysis": row["personal_analysis"],
    }


@router.get("/report/list")
def list_reports(user=Depends(get_current_user)):
    return {"dates": report_model.list_report_dates(user["id"])}


@router.get("/report/today")
def report_today(user=Depends(get_current_user)):
    row = report_model.get_today_report(user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="no report today")
    return _serialize(row)


@router.get("/report/{date}")
def report_by_date(date: str, user=Depends(get_current_user)):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    row = report_model.get_report(user["id"], date)
    if not row:
        raise HTTPException(status_code=404, detail="report not found")
    return _serialize(row)
```

> 路由顺序：`/report/list` 与 `/report/today` 必须定义在 `/report/{date}` **之前**，否则 `list`/`today` 会被 `{date}` 捕获。FastAPI 按声明顺序匹配，上面已保证。

- [ ] **Step 4: 挂载路由**

Edit `server/app/main.py`，在现有内容基础上增加 report 路由：

```python
from fastapi import FastAPI
from app.api import auth, portfolio, report

app = FastAPI(title="pusher-go-advanced")
app.include_router(auth.router)
app.include_router(portfolio.router)
app.include_router(report.router)
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_report_api.py -v`
Expected: PASS（5 passed）。

- [ ] **Step 6: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/api/report.py server/app/main.py server/tests/test_report_api.py
git commit -m "feat(api): add report query endpoints"
```

---

## Task 3: 邮件发送

**Files:**
- Create: `server/app/pipeline/__init__.py`, `server/app/pipeline/email.py`
- Test: `server/tests/test_email.py`

**Interfaces:**
- Consumes: `app.config.load_settings`。
- Produces:
  - `app.pipeline.email.build_message(from_addr, to_addr, subject, html) -> email.message.EmailMessage`。
  - `app.pipeline.email.send_report_email(to_addr, subject, html, smtp_factory=None) -> None` — 用 `settings` 的 SMTP 配置发信；`smtp_factory` 可注入（默认 `smtplib.SMTP`），便于测试。失败抛异常。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_email.py`:

```python
import pytest
from app.pipeline import email as email_mod


def test_build_message_sets_headers_and_html():
    msg = email_mod.build_message("from@x.com", "to@y.com", "标题", "<h1>hi</h1>")
    assert msg["From"] == "from@x.com"
    assert msg["To"] == "to@y.com"
    assert msg["Subject"] == "标题"
    assert msg.get_content_type() == "text/html"
    assert "<h1>hi</h1>" in msg.get_content()


def test_send_report_email_uses_smtp(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "x")
    monkeypatch.setenv("MYSQL_USER", "x")
    monkeypatch.setenv("MYSQL_PASSWORD", "x")
    monkeypatch.setenv("MYSQL_DATABASE", "x")
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.test")
    monkeypatch.setenv("EMAIL_SMTP_PORT", "587")
    monkeypatch.setenv("EMAIL_FROM", "from@x.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")

    events = []

    class FakeSMTP:
        def __init__(self, host, port):
            events.append(("init", host, port))
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def starttls(self):
            events.append(("starttls",))
        def login(self, user, pw):
            events.append(("login", user, pw))
        def send_message(self, msg):
            events.append(("send", msg["To"]))

    email_mod.send_report_email("to@y.com", "主题", "<p>x</p>", smtp_factory=FakeSMTP)

    assert ("init", "smtp.test", 587) in events
    assert ("starttls",) in events
    assert ("login", "from@x.com", "secret") in events
    assert ("send", "to@y.com") in events


def test_send_report_email_propagates_failure(monkeypatch):
    for k in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("EMAIL_FROM", "from@x.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")

    class BoomSMTP:
        def __init__(self, *a):
            raise RuntimeError("smtp down")

    with pytest.raises(RuntimeError):
        email_mod.send_report_email("to@y.com", "s", "<p>x</p>", smtp_factory=BoomSMTP)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_email.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.pipeline'`。

- [ ] **Step 3: 写实现**

Create `server/app/pipeline/__init__.py` (空文件):

```python
```

Create `server/app/pipeline/email.py`:

```python
import smtplib
from email.message import EmailMessage
from app.config import load_settings


def build_message(from_addr, to_addr, subject, html) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content("请使用支持 HTML 的邮件客户端查看本报告。")
    msg.add_alternative(html, subtype="html")
    return msg


def send_report_email(to_addr, subject, html, smtp_factory=None) -> None:
    s = load_settings()
    factory = smtp_factory or smtplib.SMTP
    msg = build_message(s.email_from, to_addr, subject, html)
    with factory(s.email_smtp_host, s.email_smtp_port) as client:
        client.starttls()
        client.login(s.email_from, s.email_password)
        client.send_message(msg)
```

> 注：`add_alternative(html, subtype="html")` 后，`get_content_type()` 在 `multipart/alternative` 下不直接是 `text/html`。为让 `test_build_message_sets_headers_and_html` 的断言成立，这里改为**只设 HTML 正文**：把 `set_content("...")` 一行删掉，改用 `msg.set_content(html, subtype="html")`。更新后的 `build_message`：

```python
def build_message(from_addr, to_addr, subject, html) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(html, subtype="html")
    return msg
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_email.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 运行全部测试**

Run: `cd server && python3 -m pytest -v`
Expected: 全绿（子计划 1/2/3/4 累计测试全部通过）。

- [ ] **Step 6: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/pipeline/__init__.py server/app/pipeline/email.py server/tests/test_email.py
git commit -m "feat(email): add html report email sending with injectable smtp"
```

---

## Self-Review

**1. Spec coverage（范围 = spec v2 §5.1 report 查询三端点 + §4.x 邮件推送能力）：**
- GET /report/today、/report/{date}、/report/list → Task 2。✅
- 报告持久化（供流水线写入）→ Task 1。✅
- 邮件 HTML 推送 → Task 3。✅
- 触发流水线/job → 子计划 5。✅

**2. Placeholder 扫描：** 无占位。Task 3 Step 3 对 `build_message` 给了明确的最终版本（只设 HTML 正文），无 TBD。✅

**3. 类型一致性：** `save_report/get_report/get_today_report/list_report_dates/beijing_today` 在 model、api、测试间一致；`build_message`、`send_report_email(to_addr, subject, html, smtp_factory=None)` 签名前后一致；report 序列化字段与端点测试断言一致。✅
