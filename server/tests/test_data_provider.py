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
