import pytest
from app.db import mysql
from app.models import job


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


def test_create_job_pending():
    jid = job.create_job("manual_report", user_id=1)
    assert isinstance(jid, str) and len(jid) == 36
    row = job.get_job(jid)
    assert row["status"] == "pending"
    assert row["type"] == "manual_report"
    assert row["user_id"] == 1


def test_mark_running_done():
    jid = job.create_job("pipeline")
    job.mark_running(jid)
    assert job.get_job(jid)["status"] == "running"
    job.mark_done(jid, "2026-06-25")
    row = job.get_job(jid)
    assert row["status"] == "done"
    assert row["finished_at"] is not None
    assert row["report_date"].strftime("%Y-%m-%d") == "2026-06-25"


def test_mark_failed_records_error():
    jid = job.create_job("pipeline")
    job.mark_failed(jid, "boom happened")
    row = job.get_job(jid)
    assert row["status"] == "failed"
    assert "boom" in row["error"]
    assert row["finished_at"] is not None


def test_get_missing_returns_none():
    assert job.get_job("00000000-0000-0000-0000-000000000000") is None
