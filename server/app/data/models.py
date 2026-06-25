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
