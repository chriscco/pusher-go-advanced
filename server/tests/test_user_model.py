import pytest
from app.db import mysql
from app.models import user


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


def test_create_and_get_by_email():
    uid = user.create_user("u@x.com", "hash1", "u@x.com", "tok1")
    assert isinstance(uid, int) and uid > 0

    row = user.get_user_by_email("u@x.com")
    assert row["id"] == uid
    assert row["password"] == "hash1"
    assert row["token"] == "tok1"


def test_get_by_email_missing_returns_none():
    assert user.get_user_by_email("nobody@x.com") is None


def test_get_by_token():
    uid = user.create_user("t@x.com", "h", "t@x.com", "tokABC")
    row = user.get_user_by_token("tokABC")
    assert row["id"] == uid
    assert user.get_user_by_token("nope") is None


def test_set_user_token():
    uid = user.create_user("s@x.com", "h", "s@x.com", "old")
    user.set_user_token(uid, "new")
    assert user.get_user_by_token("old") is None
    assert user.get_user_by_token("new")["id"] == uid
