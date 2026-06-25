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
