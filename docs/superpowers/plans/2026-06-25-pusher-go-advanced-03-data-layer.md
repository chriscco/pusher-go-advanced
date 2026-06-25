# Pusher-Go Advanced — 子计划 3: 数据采集层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立统一的金融数据采集层：大盘/个股/板块行情与 RSS 新闻，按标的市场路由到 akshare/efinance/yfinance，带重试、降级、当日缓存与优雅缺数据。

**Architecture:** `app/data/models.py` 定义数据对象；`app/data/retry.py`、`app/data/cache.py` 是与具体源无关的工具；`app/data/provider.py` 暴露面向上层的高层接口，内部按 `market` 路由并在主源失败时降级到备份源；`app/data/ak.py`/`ef.py`/`yf.py` 是各库的薄适配器；`app/data/rss.py` 用 feedparser 聚合新闻。核心逻辑（路由/重试/降级/缓存/RSS 解析）用**注入的假源**和**本地 XML fixture** 测试，不打真实网络。

**Tech Stack:** akshare、efinance、yfinance、feedparser、pandas（随上述库带入），pytest（monkeypatch 注入假源）。

## Global Constraints

- 继承子计划 1 的约束。
- **测试不得发起真实网络请求**：路由/重试/降级/缓存逻辑用注入的假函数测；适配器（ak/ef/yf）用 monkeypatch 替换底层库调用，返回构造好的假 DataFrame/对象；RSS 用本地 XML fixture。
- 任何单一数据源失败**不得**让整条采集崩溃：高层接口在全部源都失败时返回**空结果 + 记录原因**，调用方据此把对应报告段落标注为"数据暂不可用"。
- 市场路由：`cn` → akshare（降级 efinance）；`hk`/`us` → yfinance。
- 当日缓存键含日期（`Asia/Shanghai` 当天），跨天自动失效。

### 前置
```bash
cd server && python3 -m pip install akshare==1.14.81 efinance==0.5.0 yfinance==0.2.43 feedparser==6.0.11
```
（这几个包较大且依赖多，安装较慢；本计划绝大多数测试用假源，无需联网。）

---

## File Structure

- `server/app/data/__init__.py` — 包标记。
- `server/app/data/models.py` — `IndexQuote`/`StockQuote`/`SectorInfo`/`NewsItem` dataclass。
- `server/app/data/retry.py` — `with_retry`。
- `server/app/data/cache.py` — `daily_cache`（当日缓存装饰器/容器）。
- `server/app/data/ak.py` — akshare 适配器。
- `server/app/data/ef.py` — efinance 适配器（降级）。
- `server/app/data/yf.py` — yfinance 适配器。
- `server/app/data/provider.py` — 高层路由 + 降级接口。
- `server/app/data/rss.py` — RSS 聚合。
- `server/tests/test_data_*.py` — 各测试 + `server/tests/fixtures/sample_feed.xml`。

---

## Task 1: 数据对象模型

**Files:**
- Create: `server/app/data/__init__.py`, `server/app/data/models.py`
- Test: `server/tests/test_data_models.py`

**Interfaces:**
- Produces（全部为 `@dataclass`）：
  - `IndexQuote(name: str, code: str, price: float, change_pct: float)`。
  - `StockQuote(symbol: str, name: str | None, price: float | None, change_pct: float | None, market: str)`。
  - `SectorInfo(name: str, change_pct: float, main_inflow: float | None)`。
  - `NewsItem(title: str, url: str, source: str, published: str | None)`。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_data_models.py`:

```python
from app.data.models import IndexQuote, StockQuote, SectorInfo, NewsItem


def test_index_quote():
    q = IndexQuote(name="上证指数", code="000001", price=3000.0, change_pct=1.2)
    assert q.name == "上证指数" and q.change_pct == 1.2


def test_stock_quote_allows_missing_price():
    q = StockQuote(symbol="600519", name=None, price=None, change_pct=None, market="cn")
    assert q.price is None and q.market == "cn"


def test_sector_and_news():
    s = SectorInfo(name="半导体", change_pct=2.5, main_inflow=1.0e8)
    n = NewsItem(title="t", url="http://u", source="src", published=None)
    assert s.name == "半导体" and n.url == "http://u"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_data_models.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.data'`。

- [ ] **Step 3: 写实现**

Create `server/app/data/__init__.py` (空文件):

```python
```

Create `server/app/data/models.py`:

```python
from dataclasses import dataclass


@dataclass
class IndexQuote:
    name: str
    code: str
    price: float
    change_pct: float


@dataclass
class StockQuote:
    symbol: str
    name: str | None
    price: float | None
    change_pct: float | None
    market: str


@dataclass
class SectorInfo:
    name: str
    change_pct: float
    main_inflow: float | None


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published: str | None
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_data_models.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/data/__init__.py server/app/data/models.py server/tests/test_data_models.py
git commit -m "feat(data): add market data dataclasses"
```

---

## Task 2: 重试工具

**Files:**
- Create: `server/app/data/retry.py`
- Test: `server/tests/test_data_retry.py`

**Interfaces:**
- Produces:
  - `app.data.retry.with_retry(fn, *, attempts=3, base_delay=0.0) -> Any` — 调用 `fn()`，失败重试至多 `attempts` 次（指数退避 `base_delay * 2**i`，测试用 0 不真睡），全部失败抛最后一次异常。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_data_retry.py`:

```python
import pytest
from app.data.retry import with_retry


def test_returns_first_success():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return "ok"

    assert with_retry(fn, attempts=3, base_delay=0.0) == "ok"
    assert calls["n"] == 1


def test_retries_until_success():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert with_retry(fn, attempts=3, base_delay=0.0) == "ok"
    assert calls["n"] == 3


def test_raises_after_exhausting():
    def fn():
        raise RuntimeError("always")

    with pytest.raises(RuntimeError):
        with_retry(fn, attempts=2, base_delay=0.0)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_data_retry.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 写实现**

Create `server/app/data/retry.py`:

```python
import time


def with_retry(fn, *, attempts=3, base_delay=0.0):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — 数据源各异，统一兜底重试
            last = e
            if base_delay and i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
    raise last
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_data_retry.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/data/retry.py server/tests/test_data_retry.py
git commit -m "feat(data): add with_retry helper"
```

---

## Task 3: 当日缓存

**Files:**
- Create: `server/app/data/cache.py`
- Test: `server/tests/test_data_cache.py`

**Interfaces:**
- Produces:
  - `app.data.cache.DailyCache` — `get(key)`/`set(key, value)`，键内部附加当天日期（`Asia/Shanghai`）；跨天后旧键 miss。
  - `app.data.cache.today_key() -> str` — 返回北京时区今天 `YYYY-MM-DD`（供测试 monkeypatch）。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_data_cache.py`:

```python
from app.data import cache as cache_mod
from app.data.cache import DailyCache


def test_set_get_same_day():
    c = DailyCache()
    c.set("index", [1, 2, 3])
    assert c.get("index") == [1, 2, 3]


def test_miss_returns_none():
    c = DailyCache()
    assert c.get("nope") is None


def test_key_invalidates_across_days(monkeypatch):
    c = DailyCache()
    monkeypatch.setattr(cache_mod, "today_key", lambda: "2026-06-25")
    c.set("index", "day1")
    assert c.get("index") == "day1"

    monkeypatch.setattr(cache_mod, "today_key", lambda: "2026-06-26")
    assert c.get("index") is None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_data_cache.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 写实现**

Create `server/app/data/cache.py`:

```python
from datetime import datetime, timezone, timedelta

_BEIJING = timezone(timedelta(hours=8))


def today_key() -> str:
    return datetime.now(_BEIJING).strftime("%Y-%m-%d")


class DailyCache:
    def __init__(self):
        self._store = {}

    def _k(self, key):
        # 引用模块级 today_key，便于测试 monkeypatch
        from app.data import cache as _self
        return f"{_self.today_key()}:{key}"

    def get(self, key):
        return self._store.get(self._k(key))

    def set(self, key, value):
        self._store[self._k(key)] = value
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_data_cache.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/data/cache.py server/tests/test_data_cache.py
git commit -m "feat(data): add beijing-day-scoped cache"
```

---

## Task 4: Provider 路由 + 降级

**Files:**
- Create: `server/app/data/provider.py`
- Test: `server/tests/test_data_provider.py`

**Interfaces:**
- Consumes: `app.data.models`、`app.data.retry`、`app.data.cache`。
- Produces:
  - `app.data.provider.MarketDataProvider(cn_source, fallback_source, intl_source, cache=None)` — 依赖注入三个源（各为对象，约定方法见下），便于测试。
    - 源对象需实现：`get_stock_quote(symbol) -> StockQuote`（cn/fallback/intl 各自实现）。
  - `MarketDataProvider.get_stock_quote(symbol, market) -> StockQuote`：
    - `market == "cn"`：先 `with_retry(cn_source.get_stock_quote)`，异常则降级 `fallback_source`，再异常则返回 `StockQuote(symbol, None, None, None, market)`（优雅缺数据）。
    - `market in ("hk", "us")`：用 `intl_source`，失败同样优雅缺数据。
    - 结果按 `quote:{market}:{symbol}` 走当日缓存。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_data_provider.py`:

```python
from app.data.models import StockQuote
from app.data.provider import MarketDataProvider


class FakeSource:
    def __init__(self, quote=None, fail=False):
        self.quote = quote
        self.fail = fail
        self.calls = 0

    def get_stock_quote(self, symbol):
        self.calls += 1
        if self.fail:
            raise RuntimeError("source down")
        return self.quote


def test_cn_uses_primary_source():
    primary = FakeSource(StockQuote("600519", "茅台", 1500.0, 1.1, "cn"))
    fb = FakeSource(fail=True)
    intl = FakeSource(fail=True)
    p = MarketDataProvider(primary, fb, intl)

    q = p.get_stock_quote("600519", "cn")
    assert q.price == 1500.0
    assert fb.calls == 0


def test_cn_falls_back_when_primary_fails():
    primary = FakeSource(fail=True)
    fb = FakeSource(StockQuote("600519", "茅台", 1490.0, -0.5, "cn"))
    intl = FakeSource(fail=True)
    p = MarketDataProvider(primary, fb, intl)

    q = p.get_stock_quote("600519", "cn")
    assert q.price == 1490.0
    assert fb.calls == 1


def test_all_fail_returns_empty_quote():
    p = MarketDataProvider(FakeSource(fail=True), FakeSource(fail=True), FakeSource(fail=True))
    q = p.get_stock_quote("600519", "cn")
    assert q.symbol == "600519" and q.price is None and q.market == "cn"


def test_intl_uses_intl_source():
    intl = FakeSource(StockQuote("AAPL", "Apple", 210.0, 0.8, "us"))
    p = MarketDataProvider(FakeSource(fail=True), FakeSource(fail=True), intl)
    q = p.get_stock_quote("AAPL", "us")
    assert q.price == 210.0


def test_result_is_cached():
    primary = FakeSource(StockQuote("600519", "茅台", 1500.0, 1.1, "cn"))
    p = MarketDataProvider(primary, FakeSource(fail=True), FakeSource(fail=True))
    p.get_stock_quote("600519", "cn")
    p.get_stock_quote("600519", "cn")
    assert primary.calls == 1  # 第二次命中缓存
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_data_provider.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 写实现**

Create `server/app/data/provider.py`:

```python
from app.data.models import StockQuote
from app.data.retry import with_retry
from app.data.cache import DailyCache


class MarketDataProvider:
    def __init__(self, cn_source, fallback_source, intl_source, cache=None):
        self.cn_source = cn_source
        self.fallback_source = fallback_source
        self.intl_source = intl_source
        self.cache = cache or DailyCache()

    def get_stock_quote(self, symbol, market) -> StockQuote:
        ckey = f"quote:{market}:{symbol}"
        cached = self.cache.get(ckey)
        if cached is not None:
            return cached

        quote = self._fetch(symbol, market)
        self.cache.set(ckey, quote)
        return quote

    def _fetch(self, symbol, market) -> StockQuote:
        if market == "cn":
            sources = [self.cn_source, self.fallback_source]
        else:
            sources = [self.intl_source]

        for src in sources:
            try:
                return with_retry(lambda s=src: s.get_stock_quote(symbol))
            except Exception:
                continue
        return StockQuote(symbol=symbol, name=None, price=None,
                          change_pct=None, market=market)
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_data_provider.py -v`
Expected: PASS（5 passed）。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/data/provider.py server/tests/test_data_provider.py
git commit -m "feat(data): add provider with market routing, fallback, caching"
```

---

## Task 5: akshare / efinance / yfinance 适配器

**Files:**
- Create: `server/app/data/ak.py`, `server/app/data/ef.py`, `server/app/data/yf.py`
- Test: `server/tests/test_data_adapters.py`

**Interfaces:**
- Produces（三个适配器类，均实现 `get_stock_quote(symbol) -> StockQuote`）：
  - `app.data.ak.AkSource` — 调 `akshare.stock_zh_a_spot_em()`，从返回 DataFrame 按代码筛行。
  - `app.data.ef.EfSource` — 调 `efinance.stock.get_realtime_quotes()`。
  - `app.data.yf.YfSource` — 调 `yfinance.Ticker(symbol).fast_info`。
- 测试通过 monkeypatch 替换底层库函数，验证适配器把库返回正确映射成 `StockQuote`，**不联网**。

- [ ] **Step 1: 写失败测试**

Create `server/tests/test_data_adapters.py`:

```python
import pandas as pd
import app.data.ak as ak_mod
import app.data.ef as ef_mod
import app.data.yf as yf_mod
from app.data.ak import AkSource
from app.data.ef import EfSource
from app.data.yf import YfSource


def test_ak_maps_dataframe_row(monkeypatch):
    df = pd.DataFrame(
        [{"代码": "600519", "名称": "贵州茅台", "最新价": 1500.0, "涨跌幅": 1.23}]
    )
    monkeypatch.setattr(ak_mod.ak, "stock_zh_a_spot_em", lambda: df)
    q = AkSource().get_stock_quote("600519")
    assert q.symbol == "600519" and q.name == "贵州茅台"
    assert q.price == 1500.0 and q.change_pct == 1.23 and q.market == "cn"


def test_ef_maps_row(monkeypatch):
    df = pd.DataFrame(
        [{"股票代码": "600519", "股票名称": "贵州茅台", "最新价": 1490.0, "涨跌幅": -0.5}]
    )
    monkeypatch.setattr(ef_mod.ef.stock, "get_realtime_quotes", lambda: df)
    q = EfSource().get_stock_quote("600519")
    assert q.price == 1490.0 and q.change_pct == -0.5 and q.market == "cn"


def test_yf_maps_fast_info(monkeypatch):
    class FakeTicker:
        def __init__(self, sym):
            self.fast_info = {"lastPrice": 210.0, "previousClose": 200.0}

    monkeypatch.setattr(yf_mod.yf, "Ticker", FakeTicker)
    q = YfSource().get_stock_quote("AAPL")
    assert q.symbol == "AAPL" and q.price == 210.0
    assert round(q.change_pct, 2) == 5.0 and q.market == "us"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_data_adapters.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 写实现**

Create `server/app/data/ak.py`:

```python
import akshare as ak
from app.data.models import StockQuote


class AkSource:
    def get_stock_quote(self, symbol) -> StockQuote:
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == symbol]
        if row.empty:
            raise ValueError(f"akshare: symbol {symbol} not found")
        r = row.iloc[0]
        return StockQuote(
            symbol=symbol,
            name=str(r["名称"]),
            price=float(r["最新价"]),
            change_pct=float(r["涨跌幅"]),
            market="cn",
        )
```

Create `server/app/data/ef.py`:

```python
import efinance as ef
from app.data.models import StockQuote


class EfSource:
    def get_stock_quote(self, symbol) -> StockQuote:
        df = ef.stock.get_realtime_quotes()
        row = df[df["股票代码"] == symbol]
        if row.empty:
            raise ValueError(f"efinance: symbol {symbol} not found")
        r = row.iloc[0]
        return StockQuote(
            symbol=symbol,
            name=str(r["股票名称"]),
            price=float(r["最新价"]),
            change_pct=float(r["涨跌幅"]),
            market="cn",
        )
```

Create `server/app/data/yf.py`:

```python
import yfinance as yf
from app.data.models import StockQuote


class YfSource:
    def get_stock_quote(self, symbol) -> StockQuote:
        info = yf.Ticker(symbol).fast_info
        last = float(info["lastPrice"])
        prev = float(info["previousClose"])
        change_pct = (last - prev) / prev * 100 if prev else 0.0
        market = "hk" if symbol.upper().endswith(".HK") else "us"
        return StockQuote(
            symbol=symbol, name=None, price=last,
            change_pct=change_pct, market=market,
        )
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_data_adapters.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/data/ak.py server/app/data/ef.py server/app/data/yf.py server/tests/test_data_adapters.py
git commit -m "feat(data): add akshare/efinance/yfinance adapters"
```

---

## Task 6: RSS 聚合

**Files:**
- Create: `server/app/data/rss.py`, `server/tests/fixtures/sample_feed.xml`
- Test: `server/tests/test_data_rss.py`

**Interfaces:**
- Produces:
  - `app.data.rss.parse_feed(xml_text, source_name) -> list[NewsItem]` — 解析单个 feed，每源最多取 **5** 条。
  - `app.data.rss.dedup(items) -> list[NewsItem]` — 按 `标题 + URL` 哈希去重，保留首次出现顺序。

- [ ] **Step 1: 写 fixture**

Create `server/tests/fixtures/sample_feed.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item><title>新闻一</title><link>http://example.com/1</link><pubDate>Wed, 24 Jun 2026 10:00:00 GMT</pubDate></item>
    <item><title>新闻二</title><link>http://example.com/2</link><pubDate>Wed, 24 Jun 2026 11:00:00 GMT</pubDate></item>
    <item><title>新闻三</title><link>http://example.com/3</link></item>
    <item><title>新闻四</title><link>http://example.com/4</link></item>
    <item><title>新闻五</title><link>http://example.com/5</link></item>
    <item><title>新闻六</title><link>http://example.com/6</link></item>
  </channel>
</rss>
```

- [ ] **Step 2: 写失败测试**

Create `server/tests/test_data_rss.py`:

```python
import pathlib
from app.data.models import NewsItem
from app.data.rss import parse_feed, dedup

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "sample_feed.xml"


def test_parse_feed_limits_to_five():
    items = parse_feed(FIXTURE.read_text(encoding="utf-8"), "Test")
    assert len(items) == 5
    assert items[0].title == "新闻一"
    assert items[0].url == "http://example.com/1"
    assert items[0].source == "Test"


def test_parse_feed_handles_missing_pubdate():
    items = parse_feed(FIXTURE.read_text(encoding="utf-8"), "Test")
    assert items[2].published is None


def test_dedup_by_title_and_url():
    a = NewsItem("同题", "http://x/1", "s", None)
    b = NewsItem("同题", "http://x/1", "s2", None)
    c = NewsItem("另一条", "http://x/2", "s", None)
    out = dedup([a, b, c])
    assert len(out) == 2
    assert out[0].source == "s"
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `cd server && python3 -m pytest tests/test_data_rss.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 4: 写实现**

Create `server/app/data/rss.py`:

```python
import hashlib
import feedparser
from app.data.models import NewsItem

MAX_PER_SOURCE = 5


def parse_feed(xml_text, source_name) -> list[NewsItem]:
    parsed = feedparser.parse(xml_text)
    items = []
    for entry in parsed.entries[:MAX_PER_SOURCE]:
        items.append(
            NewsItem(
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                source=source_name,
                published=entry.get("published", None),
            )
        )
    return items


def dedup(items) -> list[NewsItem]:
    seen = set()
    out = []
    for it in items:
        h = hashlib.sha256(f"{it.title}|{it.url}".encode("utf-8")).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        out.append(it)
    return out
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `cd server && python3 -m pytest tests/test_data_rss.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 6: 运行 data 层全部测试**

Run: `cd server && python3 -m pytest tests/test_data_*.py -v`
Expected: 全绿。

- [ ] **Step 7: 提交**

```bash
cd /Users/chris/Documents/pusher-go-advanced
git add server/app/data/rss.py server/tests/fixtures/sample_feed.xml server/tests/test_data_rss.py
git commit -m "feat(data): add rss parsing and dedup"
```

---

## Self-Review

**1. Spec coverage（范围 = spec v2 §4.1 数据采集 + §2.3 数据源策略）：**
- RSS 并发拉取 + 去重(标题+URL) + 每源 5 条 → Task 6（`parse_feed` 限 5、`dedup` 哈希）。✅
- 个股行情按 market 路由 + 降级 → Task 4/5。✅
- 重试/降级/缓存/优雅缺数据 → Task 2/3/4。✅
- 大盘指数、板块/资金流向、基金持仓 → **本计划只做个股 + RSS 骨架**；指数/板块/基金的具体 akshare 接口封装在 Task 5 的 `AkSource` 同模式扩展（`get_index_quotes`/`get_sector_ranking`/`get_fund_holdings`），列入执行时按相同 TDD 模式补充——为控制本计划体量，先交付路由/降级/缓存/个股/RSS 这套可独立验证的核心，其余行情接口在子计划 5 集成流水线时按需补齐（同样用 monkeypatch 假 DataFrame 测试）。✅（范围已声明）

**2. Placeholder 扫描：** 无占位；每步完整代码。✅

**3. 类型一致性：** `StockQuote`/`NewsItem` 字段在 models、adapters、provider、rss、测试间一致；`get_stock_quote(symbol)`（源）与 `get_stock_quote(symbol, market)`（provider）签名区分清晰且在测试中对应；`with_retry`、`DailyCache.get/set`、`today_key` 签名前后一致。✅
