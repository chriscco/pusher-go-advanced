import datetime
import pytest
from app.db import mysql
from app.models import user, report


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


@pytest.fixture
def uid():
    return user.create_user("r@x.com", "h", "r@x.com", "tok")


def test_save_and_get(uid):
    rid = report.save_report(uid, "2026-06-24", "<h1>r</h1>", "news", "stock", "me")
    assert isinstance(rid, int) and rid > 0
    row = report.get_report(uid, "2026-06-24")
    assert row["content"] == "<h1>r</h1>"
    assert row["news_summary"] == "news"


def test_get_missing_returns_none(uid):
    assert report.get_report(uid, "2099-01-01") is None


def test_get_today(uid, monkeypatch):
    today = datetime.date(2026, 6, 25)
    monkeypatch.setattr(report, "beijing_today", lambda: today)
    report.save_report(uid, today, "<p>today</p>", "n", "s", "p")
    row = report.get_today_report(uid)
    assert row["content"] == "<p>today</p>"


def test_list_dates_descending(uid):
    report.save_report(uid, "2026-06-22", "a", "n", "s", "p")
    report.save_report(uid, "2026-06-24", "b", "n", "s", "p")
    report.save_report(uid, "2026-06-23", "c", "n", "s", "p")
    assert report.list_report_dates(uid) == ["2026-06-24", "2026-06-23", "2026-06-22"]
