# Pusher-Go Advanced — 子计划 5: Agentic AI 流水线 + 异步 Job Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把数据采集（子计划 3）、多 Agent AI、报告持久化与邮件（子计划 4）编排成一条完整流水线，并通过 jobs 表 + 后台任务实现"触发即返回 job_id、后台异步执行、轮询查状态"。

**Architecture:** `app/models/job.py` 维护 job 状态机；`app/agents/llm.py` 封装 DeepSeek（OpenAI 兼容）调用与模型配置层级；`app/agents/*.py` 是各 Agent（注入 `chat_fn` 便于测试）；`app/data/market.py` 补齐指数/板块行情与 RSS 抓取；`app/pipeline/pipeline.py` 编排全流程；`app/api/job.py`/`app/api/timer.py` 提供触发与查询端点，用 FastAPI `BackgroundTasks` 异步执行。所有 LLM/网络调用在测试中以注入的假实现替换。

**Tech Stack:** httpx（调用 DeepSeek）、FastAPI BackgroundTasks、PyMySQL、子计划 3 的 provider/rss、子计划 4 的 report/email。

## Global Constraints

- 继承子计划 1–4 的全部约束与产物。
- **测试零真实网络/LLM 调用**：`chat_fn`、`email_sender`、`provider`、RSS `fetcher`、akshare 函数全部以注入或 monkeypatch 替换。
- job 状态机：`pending → running → done|failed`，失败必须把异常文本写入 `jobs.error`，并置 `finished_at`。
- 流水线对单个用户/单个数据源失败要隔离：一个用户的报告失败不影响其他用户；缺数据段落标注"数据暂不可用"。
- 模型配置层级遵循 spec v2 §4.3：`user.model_key` 非空则用用户配置，否则用环境默认；Planner 用 `PLANNER_MODEL`，其余用 `DEEPSEEK_MODEL`。

### 前置
依赖子计划 1（db/config）、2（user/portfolio/main）、3（provider/rss）、4（report/email）。测试用本地 MySQL 测试库。`httpx` 已在子计划 2 装好。

---

## File Structure

- `server/app/models/job.py` — job 状态机。
- `server/app/models/user.py` — **修改**：新增 `list_all_users`。
- `server/app/agents/__init__.py` — 包标记。
- `server/app/agents/llm.py` — DeepSeek 调用 + `resolve_model_config`。
- `server/app/agents/agents.py` — 六个 Agent 函数。
- `server/app/data/market.py` — 指数/板块行情 + RSS 抓取。
- `server/app/pipeline/pipeline.py` — 流水线编排 + `run_job`。
- `server/app/api/job.py` — `/trigger-report`、`/job/{id}`。
- `server/app/api/timer.py` — `/internal/timer`。
- `server/app/main.py` — **修改**：挂载 job、timer 路由。
- `server/tests/test_job_model.py`、`test_llm.py`、`test_agents.py`、`test_market.py`、`test_pipeline.py`、`test_job_api.py` — 测试。

---

## Task 1: Job 状态机模型

**Files:**
- Create: `server/app/models/job.py`
- Test: `server/tests/test_job_model.py`

**Interfaces:**
- Consumes: `app.db.mysql`。
- Produces:
  - `app.models.job.create_job(type_, user_id=None) -> str`（返回 UUID 字符串，初始 `pending`）。
  - `app.models.job.get_job(job_id) -> dict | None`。
  - `app.models.job.mark_running(job_id) -> None`。
  - `app.models.job.mark_done(job_id, report_date) -> None`。
  - `app.models.job.mark_failed(job_id, error) -> None`。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_job_model.py`:

```python
import pytest
from app.db import mysql
from app.models import job


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


def test_create_job_pending():
    jid = job.create_job("manual_report", user_id=1)
    assert isinstance(jid, str) and len(jid) == 36
    row = job.get_job(jid)
    assert row["status"] == "pending"
    assert row["type"] == "manual_report"
    assert row["user_id"] == 1


def test_mark_running_done():
    jid = job.create_job("pipeline")
    job.mark_running(jid)
    assert job.get_job(jid)["status"] == "running"
    job.mark_done(jid, "2026-06-25")
    row = job.get_job(jid)
    assert row["status"] == "done"
    assert row["finished_at"] is not None
    assert row["report_date"].strftime("%Y-%m-%d") == "2026-06-25"


def test_mark_failed_records_error():
    jid = job.create_job("pipeline")
    job.mark_failed(jid, "boom happened")
    row = job.get_job(jid)
    assert row["status"] == "failed"
    assert "boom" in row["error"]
    assert row["finished_at"] is not None


def test_get_missing_returns_none():
    assert job.get_job("00000000-0000-0000-0000-000000000000") is None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_job_model.py -v`
Expected: FAIL，`ImportError`。

- [ ] **Step 3: 写实现**

Create `server/app/models/job.py`:

```python
import uuid
from app.db import mysql


def create_job(type_, user_id=None) -> str:
    job_id = str(uuid.uuid4())
    mysql.execute(
        "INSERT INTO jobs (id, user_id, type, status) VALUES (%s, %s, %s, 'pending')",
        (job_id, user_id, type_),
    )
    return job_id


def get_job(job_id):
    rows = mysql.query("SELECT * FROM jobs WHERE id = %s", (job_id,))
    return rows[0] if rows else None


def mark_running(job_id) -> None:
    mysql.execute("UPDATE jobs SET status = 'running' WHERE id = %s", (job_id,))


def mark_done(job_id, report_date) -> None:
    mysql.execute(
        "UPDATE jobs SET status = 'done', report_date = %s, finished_at = NOW() "
        "WHERE id = %s",
        (report_date, job_id),
    )


def mark_failed(job_id, error) -> None:
    mysql.execute(
        "UPDATE jobs SET status = 'failed', error = %s, finished_at = NOW() "
        "WHERE id = %s",
        (str(error), job_id),
    )
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_job_model.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/models/job.py server/tests/test_job_model.py
git commit -m "feat(models): add job state machine"
```

---

## Task 2: LLM 客户端 + 模型配置层级

**Files:**
- Create: `server/app/agents/__init__.py`, `server/app/agents/llm.py`
- Test: `server/tests/test_llm.py`

**Interfaces:**
- Consumes: `app.config.load_settings`。
- Produces:
  - `app.agents.llm.chat(messages, model, *, api_key=None, endpoint=None, poster=None) -> str` — 调 OpenAI 兼容 `/chat/completions`，返回首条回复文本。`poster(url, headers, payload) -> dict` 可注入。
  - `app.agents.llm.resolve_model_config(user) -> dict`（键 `api_key`/`endpoint`；用户 `model_key` 非空则用用户配置，否则环境默认）。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_llm.py`:

```python
import pytest
from app.agents import llm


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")


def test_chat_returns_first_message():
    captured = {}

    def poster(url, headers, payload):
        captured["url"] = url
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "hello world"}}]}

    out = llm.chat([{"role": "user", "content": "hi"}], "deepseek-chat", poster=poster)
    assert out == "hello world"
    assert captured["url"].endswith("/chat/completions")
    assert captured["payload"]["model"] == "deepseek-chat"


def test_resolve_uses_env_default_when_no_user_key():
    cfg = llm.resolve_model_config({"model_key": None})
    assert cfg["api_key"] == "env-key"


def test_resolve_uses_user_key_when_present():
    cfg = llm.resolve_model_config(
        {"model_key": "user-key", "model_endpoint": "https://my.endpoint"}
    )
    assert cfg["api_key"] == "user-key"
    assert cfg["endpoint"] == "https://my.endpoint"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_llm.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.agents'`。

- [ ] **Step 3: 写实现**

Create `server/app/agents/__init__.py` (空文件):

```python
```

Create `server/app/agents/llm.py`:

```python
import httpx
from app.config import load_settings

_DEFAULT_ENDPOINT = "https://api.deepseek.com"


def _default_poster(url, headers, payload) -> dict:
    resp = httpx.post(url, headers=headers, json=payload, timeout=120.0)
    resp.raise_for_status()
    return resp.json()


def chat(messages, model, *, api_key=None, endpoint=None, poster=None) -> str:
    s = load_settings()
    api_key = api_key or s.deepseek_api_key
    endpoint = (endpoint or _DEFAULT_ENDPOINT).rstrip("/")
    poster = poster or _default_poster
    url = f"{endpoint}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages}
    data = poster(url, headers, payload)
    return data["choices"][0]["message"]["content"]


def resolve_model_config(user) -> dict:
    s = load_settings()
    if user and user.get("model_key"):
        return {
            "api_key": user["model_key"],
            "endpoint": user.get("model_endpoint") or _DEFAULT_ENDPOINT,
        }
    return {"api_key": s.deepseek_api_key, "endpoint": _DEFAULT_ENDPOINT}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_llm.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/agents/__init__.py server/app/agents/llm.py server/tests/test_llm.py
git commit -m "feat(agents): add deepseek llm client and model config resolution"
```

---

## Task 3: 六个 Agent 函数

**Files:**
- Create: `server/app/agents/agents.py`
- Test: `server/tests/test_agents.py`

**Interfaces:**
- Consumes: 注入的 `chat_fn(messages, model) -> str`。
- Produces（每个返回 `str`）：
  - `run_planner(events_text, portfolios_overview, chat_fn, model) -> str`。
  - `run_market_analyst(indices, sectors, chat_fn, model) -> str`（`indices: list[IndexQuote]`、`sectors: list[SectorInfo]`）。
  - `run_news_editor(news_items, chat_fn, model) -> str`（`news_items: list[NewsItem]`）。
  - `run_sector_analyst(sectors, chat_fn, model) -> str`。
  - `run_advisor(user_email, holdings_lines, chat_fn, model) -> str`（`holdings_lines: list[str]`）。
  - `run_reviewer(outline, sections, chat_fn, model) -> str`（`sections: dict[str, str]`，返回 HTML）。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_agents.py`:

```python
from app.data.models import IndexQuote, SectorInfo, NewsItem
from app.agents import agents


def make_chat(capture):
    def chat_fn(messages, model):
        capture["prompt"] = messages[-1]["content"]
        capture["model"] = model
        return "AGENT_OUTPUT"
    return chat_fn


def test_market_analyst_includes_data():
    cap = {}
    out = agents.run_market_analyst(
        [IndexQuote("上证指数", "000001", 3000.0, 1.2)],
        [SectorInfo("半导体", 2.5, 1e8)],
        make_chat(cap), "deepseek-chat",
    )
    assert out == "AGENT_OUTPUT"
    assert "上证指数" in cap["prompt"]
    assert "半导体" in cap["prompt"]
    assert cap["model"] == "deepseek-chat"


def test_news_editor_includes_titles():
    cap = {}
    agents.run_news_editor(
        [NewsItem("重大新闻", "http://u", "src", None)], make_chat(cap), "m"
    )
    assert "重大新闻" in cap["prompt"]


def test_advisor_includes_holdings():
    cap = {}
    agents.run_advisor("u@x.com", ["600519 贵州茅台 +1.2%"], make_chat(cap), "m")
    assert "600519" in cap["prompt"]


def test_reviewer_combines_sections():
    cap = {}
    out = agents.run_reviewer(
        "今日大纲",
        {"market": "M", "news": "N", "sector": "S", "advisor": "A"},
        make_chat(cap), "m",
    )
    assert out == "AGENT_OUTPUT"
    for token in ("今日大纲", "M", "N", "S", "A"):
        assert token in cap["prompt"]
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_agents.py -v`
Expected: FAIL，`ImportError`。

- [ ] **Step 3: 写实现**

Create `server/app/agents/agents.py`:

```python
def _ask(chat_fn, model, prompt):
    return chat_fn([{"role": "user", "content": prompt}], model)


def run_planner(events_text, portfolios_overview, chat_fn, model) -> str:
    prompt = (
        "你是金融日报主编。基于以下当日核心事件与全部用户持仓概览，"
        "用要点列出今日报告大纲，并标注每个用户的关注重点。\n\n"
        f"【核心事件】\n{events_text}\n\n【持仓概览】\n{portfolios_overview}\n"
    )
    return _ask(chat_fn, model, prompt)


def run_market_analyst(indices, sectors, chat_fn, model) -> str:
    idx = "\n".join(f"{i.name} {i.price} ({i.change_pct:+.2f}%)" for i in indices)
    sec = "\n".join(f"{s.name} ({s.change_pct:+.2f}%)" for s in sectors)
    prompt = (
        "你是市场分析师。根据大盘指数与板块数据写一段简明的市场概览。\n\n"
        f"【大盘】\n{idx}\n\n【板块】\n{sec}\n"
    )
    return _ask(chat_fn, model, prompt)


def run_news_editor(news_items, chat_fn, model) -> str:
    lines = "\n".join(f"- {n.title} ({n.source})" for n in news_items)
    prompt = (
        "你是新闻编辑。从以下新闻中精选 5-8 条最重要的，"
        "每条给一句简短点评。\n\n" + lines
    )
    return _ask(chat_fn, model, prompt)


def run_sector_analyst(sectors, chat_fn, model) -> str:
    sec = "\n".join(
        f"{s.name} ({s.change_pct:+.2f}%) 主力净流入 {s.main_inflow}" for s in sectors
    )
    prompt = "你是板块轮动分析师。根据板块涨跌与资金流向分析今日热点。\n\n" + sec
    return _ask(chat_fn, model, prompt)


def run_advisor(user_email, holdings_lines, chat_fn, model) -> str:
    holdings = "\n".join(holdings_lines) if holdings_lines else "（无持仓）"
    prompt = (
        f"你是 {user_email} 的个人投资顾问。根据其持仓及当日行情，"
        "给出个性化涨跌分析与简要建议。\n\n【持仓与行情】\n" + holdings
    )
    return _ask(chat_fn, model, prompt)


def run_reviewer(outline, sections, chat_fn, model) -> str:
    body = "\n\n".join(f"## {k}\n{v}" for k, v in sections.items())
    prompt = (
        "你是主编。把以下各部分整合成一篇连贯的 HTML 日报，"
        "检查数据一致性并优化文风，直接输出完整 HTML。\n\n"
        f"【大纲】\n{outline}\n\n【素材】\n{body}\n"
    )
    return _ask(chat_fn, model, prompt)
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_agents.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/agents/agents.py server/tests/test_agents.py
git commit -m "feat(agents): add planner/analyst/editor/sector/advisor/reviewer"
```

---

## Task 4: 指数/板块行情 + RSS 抓取

**Files:**
- Create: `server/app/data/market.py`
- Test: `server/tests/test_market.py`

**Interfaces:**
- Consumes: `app.data.models`、`app.data.rss.parse_feed/dedup`、akshare。
- Produces:
  - `app.data.market.get_index_quotes(ak=None) -> list[IndexQuote]`（上证/深证/创业板，调 `ak.stock_zh_index_spot_em`）。
  - `app.data.market.get_sector_ranking(ak=None, top=10) -> list[SectorInfo]`（调 `ak.stock_board_industry_name_em`）。
  - `app.data.market.fetch_news(sources, fetcher=None) -> list[NewsItem]`（`sources: list[dict{name,url}]`；`fetcher(url) -> str` 返回 XML，可注入；内部 `parse_feed` + `dedup`；单源失败跳过）。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_market.py`:

```python
import pandas as pd
import app.data.market as market


def test_get_index_quotes(monkeypatch):
    df = pd.DataFrame([
        {"名称": "上证指数", "代码": "000001", "最新价": 3000.0, "涨跌幅": 1.2},
        {"名称": "深证成指", "代码": "399001", "最新价": 9000.0, "涨跌幅": -0.3},
        {"名称": "创业板指", "代码": "399006", "最新价": 1800.0, "涨跌幅": 0.5},
        {"名称": "其他", "代码": "999999", "最新价": 1.0, "涨跌幅": 0.0},
    ])

    class FakeAk:
        def stock_zh_index_spot_em(self):
            return df

    out = market.get_index_quotes(ak=FakeAk())
    names = {q.name for q in out}
    assert names == {"上证指数", "深证成指", "创业板指"}


def test_get_sector_ranking(monkeypatch):
    df = pd.DataFrame([
        {"板块名称": "半导体", "涨跌幅": 3.1, "主力净流入": 5e8},
        {"板块名称": "白酒", "涨跌幅": -1.2, "主力净流入": -2e8},
    ])

    class FakeAk:
        def stock_board_industry_name_em(self):
            return df

    out = market.get_sector_ranking(ak=FakeAk(), top=10)
    assert out[0].name == "半导体" and out[0].change_pct == 3.1


def test_fetch_news_skips_failing_source():
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>n1</title><link>http://a/1</link></item>"
        "</channel></rss>"
    )

    def fetcher(url):
        if "bad" in url:
            raise RuntimeError("down")
        return feed

    sources = [{"name": "good", "url": "http://good"}, {"name": "bad", "url": "http://bad"}]
    out = market.fetch_news(sources, fetcher=fetcher)
    assert len(out) == 1 and out[0].title == "n1"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_market.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 写实现**

Create `server/app/data/market.py`:

```python
from app.data.models import IndexQuote, SectorInfo
from app.data.rss import parse_feed, dedup

_INDEX_NAMES = {"上证指数", "深证成指", "创业板指"}


def get_index_quotes(ak=None) -> list[IndexQuote]:
    if ak is None:
        import akshare as ak
    df = ak.stock_zh_index_spot_em()
    out = []
    for _, r in df.iterrows():
        if str(r["名称"]) in _INDEX_NAMES:
            out.append(IndexQuote(
                name=str(r["名称"]), code=str(r["代码"]),
                price=float(r["最新价"]), change_pct=float(r["涨跌幅"]),
            ))
    return out


def get_sector_ranking(ak=None, top=10) -> list[SectorInfo]:
    if ak is None:
        import akshare as ak
    df = ak.stock_board_industry_name_em()
    out = []
    for _, r in df.head(top).iterrows():
        out.append(SectorInfo(
            name=str(r["板块名称"]),
            change_pct=float(r["涨跌幅"]),
            main_inflow=float(r["主力净流入"]) if "主力净流入" in r else None,
        ))
    return out


def fetch_news(sources, fetcher=None) -> list:
    if fetcher is None:
        import httpx

        def fetcher(url):
            return httpx.get(url, timeout=30.0).text

    items = []
    for src in sources:
        try:
            xml = fetcher(src["url"])
            items.extend(parse_feed(xml, src["name"]))
        except Exception:
            continue
    return dedup(items)
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_market.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/data/market.py server/tests/test_market.py
git commit -m "feat(data): add index/sector quotes and rss fetching"
```

---

## Task 5: 流水线编排 + run_job

**Files:**
- Create: `server/app/pipeline/pipeline.py`
- Modify: `server/app/models/user.py`（新增 `list_all_users`）
- Test: `server/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `app.agents.agents`、`app.models.user/portfolio/report/job`、`app.pipeline.email`、子计划 3 provider。
- Produces:
  - `app.models.user.list_all_users() -> list[dict]`。
  - `app.pipeline.pipeline.run_pipeline(*, bundle, provider, chat_fn, email_sender, report_date) -> int`（为每个用户生成并保存报告、发邮件，返回生成的报告数）。
    - `bundle`: `dict{indices, sectors, news}`。
  - `app.pipeline.pipeline.run_job(job_id, *, runner=None) -> None`（包裹状态机：`mark_running` → 执行 → `mark_done`/`mark_failed`；`runner` 默认 `_default_runner`，可注入）。

- [ ] **Step 1: 写 list_all_users（先加测试）**

Append to `server/tests/test_user_model.py`（在文件末尾追加）:

```python


def test_list_all_users():
    user.create_user("a@x.com", "h", "a@x.com", "t1")
    user.create_user("b@x.com", "h", "b@x.com", "t2")
    rows = user.list_all_users()
    emails = {r["email"] for r in rows}
    assert {"a@x.com", "b@x.com"}.issubset(emails)
```

Run: `cd server && python3 -m pytest tests/test_user_model.py::test_list_all_users -v`
Expected: FAIL，`AttributeError: ... has no attribute 'list_all_users'`。

Append to `server/app/models/user.py`:

```python


def list_all_users():
    return mysql.query("SELECT * FROM users ORDER BY id")
```

Run again — Expected: PASS。

- [ ] **Step 2: 写流水线失败测试**

Create `server/tests/test_pipeline.py`:

```python
import datetime
import pytest
from app.db import mysql
from app.models import user, portfolio, report
from app.data.models import IndexQuote, SectorInfo, NewsItem, StockQuote
from app.pipeline import pipeline


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


class FakeProvider:
    def get_stock_quote(self, symbol, market):
        return StockQuote(symbol, "名称", 100.0, 1.5, market)


def fake_chat(messages, model):
    return f"OUT[{messages[-1]['content'][:6]}]"


def test_run_pipeline_saves_report_and_emails():
    uid = user.create_user("u@x.com", "h", "to@x.com", "tok")
    portfolio.add_portfolio(uid, "600519", "茅台", "stock", "cn", 100, None)

    sent = []
    bundle = {
        "indices": [IndexQuote("上证指数", "000001", 3000.0, 1.2)],
        "sectors": [SectorInfo("半导体", 2.5, 1e8)],
        "news": [NewsItem("新闻", "http://u", "src", None)],
    }

    n = pipeline.run_pipeline(
        bundle=bundle,
        provider=FakeProvider(),
        chat_fn=fake_chat,
        email_sender=lambda to, subject, html: sent.append((to, subject)),
        report_date=datetime.date(2026, 6, 25),
    )

    assert n == 1
    saved = report.get_report(uid, datetime.date(2026, 6, 25))
    assert saved is not None and saved["content"].startswith("OUT[")
    assert sent == [("to@x.com", sent[0][1])]


def test_run_job_marks_done():
    from app.models import job
    jid = job.create_job("pipeline")
    pipeline.run_job(jid, runner=lambda: datetime.date(2026, 6, 25))
    row = job.get_job(jid)
    assert row["status"] == "done"
    assert row["report_date"].strftime("%Y-%m-%d") == "2026-06-25"


def test_run_job_marks_failed_on_error():
    from app.models import job
    jid = job.create_job("pipeline")

    def boom():
        raise RuntimeError("kaboom")

    pipeline.run_job(jid, runner=boom)
    row = job.get_job(jid)
    assert row["status"] == "failed"
    assert "kaboom" in row["error"]
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_pipeline.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.pipeline.pipeline'`。

- [ ] **Step 4: 写实现**

Create `server/app/pipeline/pipeline.py`:

```python
from app.config import load_settings
from app.models import user as user_model
from app.models import portfolio as pf_model
from app.models import report as report_model
from app.models import job as job_model
from app.models.report import beijing_today
from app.agents import agents
from app.agents.llm import chat as default_chat
from app.pipeline.email import send_report_email


def _holdings_lines(provider, holdings):
    lines = []
    for h in holdings:
        q = provider.get_stock_quote(h["symbol"], h["market"])
        price = "数据暂不可用" if q.price is None else f"{q.price} ({q.change_pct:+.2f}%)"
        qty = "" if h["quantity"] is None else f" 持有{h['quantity']}"
        lines.append(f"{h['symbol']} {h.get('name') or ''} {price}{qty}")
    return lines


def run_pipeline(*, bundle, provider, chat_fn, email_sender, report_date) -> int:
    s = load_settings()
    model = s.deepseek_model
    planner_model = s.planner_model

    indices = bundle["indices"]
    sectors = bundle["sectors"]
    news = bundle["news"]

    overview = ", ".join(u["email"] for u in user_model.list_all_users())
    events_text = "\n".join(f"- {n.title}" for n in news)
    outline = agents.run_planner(events_text, overview, chat_fn, planner_model)

    market_section = agents.run_market_analyst(indices, sectors, chat_fn, model)
    news_section = agents.run_news_editor(news, chat_fn, model)
    sector_section = agents.run_sector_analyst(sectors, chat_fn, model)

    count = 0
    for u in user_model.list_all_users():
        try:
            holdings = pf_model.list_portfolios(u["id"])
            advisor_section = agents.run_advisor(
                u["email"], _holdings_lines(provider, holdings), chat_fn, model
            )
            html = agents.run_reviewer(
                outline,
                {
                    "market": market_section,
                    "news": news_section,
                    "sector": sector_section,
                    "advisor": advisor_section,
                },
                chat_fn, model,
            )
            report_model.save_report(
                u["id"], report_date, html,
                news_section, market_section, advisor_section,
            )
            email_sender(u["email_to"], f"每日金融日报 {report_date}", html)
            count += 1
        except Exception:
            # 单用户失败不影响其他用户
            continue
    return count


def _default_runner():
    from app.data.provider import MarketDataProvider
    from app.data.ak import AkSource
    from app.data.ef import EfSource
    from app.data.yf import YfSource
    from app.data import market

    provider = MarketDataProvider(AkSource(), EfSource(), YfSource())
    bundle = {
        "indices": market.get_index_quotes(),
        "sectors": market.get_sector_ranking(),
        "news": market.fetch_news(_load_rss_sources()),
    }
    report_date = beijing_today()
    run_pipeline(
        bundle=bundle, provider=provider, chat_fn=default_chat,
        email_sender=send_report_email, report_date=report_date,
    )
    return report_date


def _load_rss_sources():
    from app.db import mysql
    return mysql.query(
        "SELECT name, url FROM rss_sources WHERE enabled = TRUE"
    )


def run_job(job_id, *, runner=None) -> None:
    runner = runner or _default_runner
    job_model.mark_running(job_id)
    try:
        report_date = runner()
        job_model.mark_done(job_id, report_date)
    except Exception as e:  # noqa: BLE001
        job_model.mark_failed(job_id, e)
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_pipeline.py tests/test_user_model.py -v`
Expected: PASS（pipeline 3 + user 5）。

- [ ] **Step 6: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/pipeline/pipeline.py server/app/models/user.py server/tests/test_pipeline.py server/tests/test_user_model.py
git commit -m "feat(pipeline): orchestrate agents into per-user reports with job wrapper"
```

---

## Task 6: Job/Timer 端点（异步触发）

**Files:**
- Create: `server/app/api/job.py`, `server/app/api/timer.py`
- Modify: `server/app/main.py`（挂载 job、timer 路由）
- Test: `server/tests/test_job_api.py`

**Interfaces:**
- Consumes: `app.deps.get_current_user`、`app.models.job`、`app.pipeline.pipeline.run_job`。
- Produces:
  - `POST /trigger-report`（Bearer）→ `{job_id}`（202），后台执行 `run_job`。
  - `GET /job/{id}`（Bearer）→ `{id, status, report_date, error}`；不存在 → 404。
  - `POST /internal/timer`（header `X-Timer-Secret` 校验）→ `{job_id}`（202），后台执行全量 pipeline job。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_job_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from app.db import mysql
from app.main import app
from app.models import job
import app.api.job as job_api
import app.api.timer as timer_api


@pytest.fixture(autouse=True)
def _reset(db_conn, monkeypatch):
    mysql.reset_connection()
    # 用假 run_job，避免后台真跑流水线
    monkeypatch.setattr(job_api, "run_job", lambda jid: job.mark_done(jid, "2026-06-25"))
    monkeypatch.setattr(timer_api, "run_job", lambda jid: job.mark_done(jid, "2026-06-25"))
    monkeypatch.setenv("TIMER_SECRET", "s3cr3t")
    yield
    mysql.reset_connection()


@pytest.fixture
def client():
    return TestClient(app)


def _auth(client):
    token = client.post(
        "/register", json={"email": "a@x.com", "password": "pw"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_trigger_requires_auth(client):
    assert client.post("/trigger-report").status_code == 401


def test_trigger_returns_job_id_and_runs(client):
    h = _auth(client)
    r = client.post("/trigger-report", headers=h)
    assert r.status_code == 202
    jid = r.json()["job_id"]
    # TestClient 同步执行 background task，完成后应为 done
    status = client.get(f"/job/{jid}", headers=h).json()
    assert status["status"] == "done"


def test_job_not_found(client):
    h = _auth(client)
    assert client.get("/job/nope", headers=h).status_code == 404


def test_timer_requires_secret(client):
    assert client.post("/internal/timer").status_code == 401
    ok = client.post("/internal/timer", headers={"X-Timer-Secret": "s3cr3t"})
    assert ok.status_code == 202
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_job_api.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.api.job'`。

- [ ] **Step 3: 写 job 路由**

Create `server/app/api/job.py`:

```python
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from app.deps import get_current_user
from app.models import job as job_model
from app.pipeline.pipeline import run_job

router = APIRouter()


@router.post("/trigger-report", status_code=202)
def trigger(background: BackgroundTasks, user=Depends(get_current_user)):
    job_id = job_model.create_job("manual_report", user_id=user["id"])
    background.add_task(run_job, job_id)
    return {"job_id": job_id}


@router.get("/job/{job_id}")
def job_status(job_id: str, user=Depends(get_current_user)):
    row = job_model.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    rd = row["report_date"]
    return {
        "id": row["id"],
        "status": row["status"],
        "report_date": rd.strftime("%Y-%m-%d") if rd else None,
        "error": row["error"],
    }
```

- [ ] **Step 4: 写 timer 路由**

Create `server/app/api/timer.py`:

```python
import os
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from app.models import job as job_model
from app.pipeline.pipeline import run_job

router = APIRouter()


@router.post("/internal/timer", status_code=202)
def timer(background: BackgroundTasks, x_timer_secret: str = Header(default=None)):
    expected = os.environ.get("TIMER_SECRET")
    if not expected or x_timer_secret != expected:
        raise HTTPException(status_code=401, detail="invalid timer secret")
    job_id = job_model.create_job("pipeline", user_id=None)
    background.add_task(run_job, job_id)
    return {"job_id": job_id}
```

> 注：导入 `run_job` 到各路由模块命名空间（`from app.pipeline.pipeline import run_job`），是为了让测试能 `monkeypatch.setattr(job_api, "run_job", ...)`。

- [ ] **Step 5: 挂载路由**

Edit `server/app/main.py`，最终为：

```python
from fastapi import FastAPI
from app.api import auth, portfolio, report, job, timer

app = FastAPI(title="pusher-go-advanced")
app.include_router(auth.router)
app.include_router(portfolio.router)
app.include_router(report.router)
app.include_router(job.router)
app.include_router(timer.router)
```

- [ ] **Step 6: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_job_api.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 7: 运行全部测试**

Run: `cd server && python3 -m pytest -v`
Expected: 全绿（子计划 1–5 累计全部通过）。

- [ ] **Step 8: 把 TIMER_SECRET 加入配置说明**

Edit `server/app/config.py`：在 `Settings` 增加字段 `timer_secret: str`，并在 `load_settings()` 返回中加 `timer_secret=os.environ.get("TIMER_SECRET", "")`。

> 这样部署子计划可统一从 `Settings` 读取。timer 路由当前直接读 `os.environ`，保持与测试一致；后续如需可改为读 `settings.timer_secret`。给 `Settings` 加字段不影响现有测试（新字段有默认）。

补充测试 `server/tests/test_config.py` 末尾：

```python


def test_timer_secret_optional(monkeypatch):
    for key in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
        monkeypatch.setenv(key, "x")
    monkeypatch.delenv("TIMER_SECRET", raising=False)
    assert load_settings().timer_secret == ""
```

Run: `cd server && python3 -m pytest tests/test_config.py -v` — Expected: PASS。

- [ ] **Step 9: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/api/job.py server/app/api/timer.py server/app/main.py server/app/config.py server/tests/test_job_api.py server/tests/test_config.py
git commit -m "feat(api): add async trigger-report, job status, and timer endpoints"
```

---

## Self-Review

**1. Spec coverage（范围 = spec v2 §4.2 Agentic 流水线 + §5.1 trigger/job + §5.2/5.3 timer/异步）：**
- Planner → 并行 Agent(市场/新闻/板块) → per-user 顾问 → Reviewer → HTML → 4.2 全链路 → Task 3/5。✅
- 模型配置层级(§4.3，用户 key 覆盖) → Task 2 `resolve_model_config`。✅
- 异步 job + 状态机 + 轮询 → Task 1/5/6。✅
- Timer 入口 + 鉴权 → Task 6。✅
- 单用户/单源失败隔离 + 优雅缺数据 → Task 5（per-user try/except、`_holdings_lines` 缺价标注）。✅
- 邮件推送 → 复用子计划 4 `send_report_email`，pipeline 注入调用。✅

**2. Placeholder 扫描：** 无 TBD/占位；每步完整代码与预期。`resolve_model_config` 暂未消费 `model_name`（spec 标注"预留"），符合 §4.3 预留语义。✅

**3. 类型一致性：** `chat(messages, model, *, poster=...)`、`resolve_model_config(user)`、六个 `run_*` Agent 签名、`run_pipeline(*, bundle, provider, chat_fn, email_sender, report_date)`、`run_job(job_id, *, runner=None)`、job 模型五个函数、`list_all_users` 在 Interfaces/实现/测试间一致；`bundle` 的键 `indices/sectors/news` 在 collect、pipeline、测试间一致；端点字段与测试断言一致。✅
