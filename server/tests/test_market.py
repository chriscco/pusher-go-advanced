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
