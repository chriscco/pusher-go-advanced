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
