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
