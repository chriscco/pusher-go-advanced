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
