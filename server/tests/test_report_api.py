import datetime
import pytest
from fastapi.testclient import TestClient
from app.db import mysql
from app.main import app
from app.models import user, report


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


@pytest.fixture
def client():
    return TestClient(app)


def _auth(client):
    token = client.post(
        "/register", json={"email": "a@x.com", "password": "pw"}
    ).json()["token"]
    return token, {"Authorization": f"Bearer {token}"}


def test_report_list(client):
    token, h = _auth(client)
    uid = user.get_user_by_token(token)["id"]
    report.save_report(uid, "2026-06-24", "c", "n", "s", "p")
    r = client.get("/report/list", headers=h)
    assert r.status_code == 200
    assert r.json()["dates"] == ["2026-06-24"]


def test_report_by_date(client):
    token, h = _auth(client)
    uid = user.get_user_by_token(token)["id"]
    report.save_report(uid, "2026-06-24", "<b>x</b>", "n", "s", "p")
    r = client.get("/report/2026-06-24", headers=h)
    assert r.status_code == 200
    assert r.json()["content"] == "<b>x</b>"


def test_report_by_date_bad_format(client):
    _, h = _auth(client)
    assert client.get("/report/not-a-date", headers=h).status_code == 400


def test_report_missing_404(client):
    _, h = _auth(client)
    assert client.get("/report/2099-01-01", headers=h).status_code == 404


def test_report_today(client, monkeypatch):
    token, h = _auth(client)
    uid = user.get_user_by_token(token)["id"]
    monkeypatch.setattr(report, "beijing_today", lambda: datetime.date(2026, 6, 25))
    report.save_report(uid, datetime.date(2026, 6, 25), "today", "n", "s", "p")
    r = client.get("/report/today", headers=h)
    assert r.status_code == 200 and r.json()["content"] == "today"
