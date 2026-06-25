from app.data import cache as cache_mod
from app.data.cache import DailyCache


def test_set_get_same_day():
    c = DailyCache()
    c.set("index", [1, 2, 3])
    assert c.get("index") == [1, 2, 3]


def test_miss_returns_none():
    c = DailyCache()
    assert c.get("nope") is None


def test_key_invalidates_across_days(monkeypatch):
    c = DailyCache()
    monkeypatch.setattr(cache_mod, "today_key", lambda: "2026-06-25")
    c.set("index", "day1")
    assert c.get("index") == "day1"

    monkeypatch.setattr(cache_mod, "today_key", lambda: "2026-06-26")
    assert c.get("index") is None
