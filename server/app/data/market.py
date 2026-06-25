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
