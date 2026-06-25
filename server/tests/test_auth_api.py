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


def test_register_returns_token(client):
    r = client.post("/register", json={"email": "a@x.com", "password": "pw"})
    assert r.status_code == 201
    assert len(r.json()["token"]) == 128


def test_register_duplicate_email_conflicts(client):
    client.post("/register", json={"email": "a@x.com", "password": "pw"})
    r = client.post("/register", json={"email": "a@x.com", "password": "pw"})
    assert r.status_code == 409


def test_login_success_returns_new_token(client):
    reg = client.post("/register", json={"email": "a@x.com", "password": "pw"})
    old = reg.json()["token"]
    r = client.post("/login", json={"email": "a@x.com", "password": "pw"})
    assert r.status_code == 200
    new = r.json()["token"]
    assert len(new) == 128
    assert new != old  # 登录重置 token


def test_login_wrong_password_401(client):
    client.post("/register", json={"email": "a@x.com", "password": "pw"})
    r = client.post("/login", json={"email": "a@x.com", "password": "BAD"})
    assert r.status_code == 401
