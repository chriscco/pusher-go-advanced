import hashlib
import feedparser
from app.data.models import NewsItem

MAX_PER_SOURCE = 5


def parse_feed(xml_text, source_name) -> list[NewsItem]:
    parsed = feedparser.parse(xml_text)
    items = []
    for entry in parsed.entries[:MAX_PER_SOURCE]:
        items.append(
            NewsItem(
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                source=source_name,
                published=entry.get("published", None),
            )
        )
    return items


def dedup(items) -> list[NewsItem]:
    seen = set()
    out = []
    for it in items:
        h = hashlib.sha256(f"{it.title}|{it.url}".encode("utf-8")).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        out.append(it)
    return out
