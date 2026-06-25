import datetime
import pytest
from app.db import mysql
from app.models import user, portfolio, report
from app.data.models import IndexQuote, SectorInfo, NewsItem, StockQuote
from app.pipeline import pipeline


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


class FakeProvider:
    def get_stock_quote(self, symbol, market):
        return StockQuote(symbol, "名称", 100.0, 1.5, market)


class PartialQuoteProvider:
    """Provider returning partial quotes with price but no change_pct."""
    def get_stock_quote(self, symbol, market):
        return StockQuote(symbol, "名称", 100.0, None, market)


def fake_chat(messages, model):
    return f"OUT[{messages[-1]['content'][:6]}]"


def test_run_pipeline_saves_report_and_emails():
    uid = user.create_user("u@x.com", "h", "to@x.com", "tok")
    portfolio.add_portfolio(uid, "600519", "茅台", "stock", "cn", 100, None)

    sent = []
    bundle = {
        "indices": [IndexQuote("上证指数", "000001", 3000.0, 1.2)],
        "sectors": [SectorInfo("半导体", 2.5, 1e8)],
        "news": [NewsItem("新闻", "http://u", "src", None)],
    }

    n = pipeline.run_pipeline(
        bundle=bundle,
        provider=FakeProvider(),
        chat_fn=fake_chat,
        email_sender=lambda to, subject, html: sent.append((to, subject)),
        report_date=datetime.date(2026, 6, 25),
    )

    assert n == 1
    saved = report.get_report(uid, datetime.date(2026, 6, 25))
    assert saved is not None and saved["content"].startswith("OUT[")
    assert sent == [("to@x.com", sent[0][1])]


def test_run_job_marks_done():
    from app.models import job
    jid = job.create_job("pipeline")
    pipeline.run_job(jid, runner=lambda: datetime.date(2026, 6, 25))
    row = job.get_job(jid)
    assert row["status"] == "done"
    assert row["report_date"].strftime("%Y-%m-%d") == "2026-06-25"


def test_run_job_marks_failed_on_error():
    from app.models import job
    jid = job.create_job("pipeline")

    def boom():
        raise RuntimeError("kaboom")

    pipeline.run_job(jid, runner=boom)
    row = job.get_job(jid)
    assert row["status"] == "failed"
    assert "kaboom" in row["error"]


def test_run_pipeline_handles_partial_quote_with_null_change_pct():
    """Verify that a partial quote (price set, change_pct None) doesn't crash."""
    uid = user.create_user("u@x.com", "h", "to@x.com", "tok")
    portfolio.add_portfolio(uid, "600519", "茅台", "stock", "cn", 100, None)

    sent = []
    bundle = {
        "indices": [IndexQuote("上证指数", "000001", 3000.0, 1.2)],
        "sectors": [SectorInfo("半导体", 2.5, 1e8)],
        "news": [NewsItem("新闻", "http://u", "src", None)],
    }

    n = pipeline.run_pipeline(
        bundle=bundle,
        provider=PartialQuoteProvider(),
        chat_fn=fake_chat,
        email_sender=lambda to, subject, html: sent.append((to, subject)),
        report_date=datetime.date(2026, 6, 25),
    )

    assert n == 1
    saved = report.get_report(uid, datetime.date(2026, 6, 25))
    assert saved is not None and saved["content"].startswith("OUT[")
    assert sent == [("to@x.com", sent[0][1])]
