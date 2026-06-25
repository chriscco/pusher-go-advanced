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
