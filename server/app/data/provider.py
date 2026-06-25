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
