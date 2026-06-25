import pytest
from fastapi.testclient import TestClient
from app.db import mysql
from app.main import app
from app.models import job
import app.api.job as job_api
import app.api.timer as timer_api


@pytest.fixture(autouse=True)
def _reset(db_conn, monkeypatch):
    mysql.reset_connection()
    # 用假 run_job，避免后台真跑流水线
    monkeypatch.setattr(job_api, "run_job", lambda jid: job.mark_done(jid, "2026-06-25"))
    monkeypatch.setattr(timer_api, "run_job", lambda jid: job.mark_done(jid, "2026-06-25"))
    monkeypatch.setenv("TIMER_SECRET", "s3cr3t")
    yield
    mysql.reset_connection()


@pytest.fixture
def client():
    return TestClient(app)


def _auth(client, email="a@x.com"):
    token = client.post(
        "/register", json={"email": email, "password": "pw"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_trigger_requires_auth(client):
    assert client.post("/trigger-report").status_code == 401


def test_trigger_returns_job_id_and_runs(client):
    h = _auth(client)
    r = client.post("/trigger-report", headers=h)
    assert r.status_code == 202
    jid = r.json()["job_id"]
    # TestClient 同步执行 background task，完成后应为 done
    status = client.get(f"/job/{jid}", headers=h).json()
    assert status["status"] == "done"


def test_job_not_found(client):
    h = _auth(client)
    assert client.get("/job/nope", headers=h).status_code == 404


def test_timer_requires_secret(client):
    assert client.post("/internal/timer").status_code == 401
    ok = client.post("/internal/timer", headers={"X-Timer-Secret": "s3cr3t"})
    assert ok.status_code == 202


def test_job_status_not_visible_to_other_user(client):
    alice = _auth(client, email="alice@x.com")
    r = client.post("/trigger-report", headers=alice)
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    bob = _auth(client, email="bob@x.com")
    assert client.get(f"/job/{job_id}", headers=bob).status_code == 404

    # sanity: alice can still read her own job
    assert client.get(f"/job/{job_id}", headers=alice).status_code == 200
