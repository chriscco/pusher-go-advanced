import pytest
from fastapi.testclient import TestClient
from app.db import mysql
from app.main import app


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
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


def test_requires_auth(client):
    assert client.get("/portfolio").status_code == 401


def test_add_list_delete(client):
    h = _auth(client)
    r = client.post(
        "/portfolio",
        json={"symbol": "600519", "type": "stock", "market": "cn", "quantity": 100},
        headers=h,
    )
    assert r.status_code == 201
    pid = r.json()["id"]

    lst = client.get("/portfolio", headers=h).json()
    assert len(lst) == 1
    assert lst[0]["symbol"] == "600519"

    assert client.delete(f"/portfolio/{pid}", headers=h).status_code == 204
    assert client.get("/portfolio", headers=h).json() == []


def test_default_market_is_cn(client):
    h = _auth(client)
    r = client.post("/portfolio", json={"symbol": "000001", "type": "stock"}, headers=h)
    pid = r.json()["id"]
    row = client.get("/portfolio", headers=h).json()[0]
    assert row["market"] == "cn"


def test_cannot_delete_others(client):
    h1 = _auth(client, "one@x.com")
    h2 = _auth(client, "two@x.com")
    pid = client.post(
        "/portfolio", json={"symbol": "600519", "type": "stock"}, headers=h1
    ).json()["id"]
    assert client.delete(f"/portfolio/{pid}", headers=h2).status_code == 404
