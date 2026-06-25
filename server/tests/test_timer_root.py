import pytest
from fastapi.testclient import TestClient
from app.db import mysql
from app.main import app
from app.models import job
import app.api.timer as timer_api


@pytest.fixture(autouse=True)
def _reset(db_conn, monkeypatch):
    mysql.reset_connection()
    monkeypatch.setattr(timer_api, "run_job", lambda jid: job.mark_done(jid, "2026-06-25"))
    monkeypatch.setenv("TIMER_SECRET", "s3cr3t")
    yield
    mysql.reset_connection()


@pytest.fixture
def client():
    return TestClient(app)


def test_root_timer_enqueues_with_valid_secret(client):
    r = client.post("/", json={"Type": "Timer", "Message": "s3cr3t"})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    assert job.get_job(jid)["status"] == "done"


def test_root_timer_rejects_bad_secret(client):
    r = client.post("/", json={"Type": "Timer", "Message": "wrong"})
    assert r.status_code == 401


def test_root_non_timer_rejected(client):
    r = client.post("/", json={"foo": "bar"})
    assert r.status_code == 401
