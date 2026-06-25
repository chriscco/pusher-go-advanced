import pathlib
from app.data.models import NewsItem
from app.data.rss import parse_feed, dedup

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "sample_feed.xml"


def test_parse_feed_limits_to_five():
    items = parse_feed(FIXTURE.read_text(encoding="utf-8"), "Test")
    assert len(items) == 5
    assert items[0].title == "新闻一"
    assert items[0].url == "http://example.com/1"
    assert items[0].source == "Test"


def test_parse_feed_handles_missing_pubdate():
    items = parse_feed(FIXTURE.read_text(encoding="utf-8"), "Test")
    assert items[2].published is None


def test_dedup_by_title_and_url():
    a = NewsItem("同题", "http://x/1", "s", None)
    b = NewsItem("同题", "http://x/1", "s2", None)
    c = NewsItem("另一条", "http://x/2", "s", None)
    out = dedup([a, b, c])
    assert len(out) == 2
    assert out[0].source == "s"
