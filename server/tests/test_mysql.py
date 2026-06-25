import pytest
from app.db import mysql


@pytest.fixture(autouse=True)
def _reset_global_conn():
    # 每个测试前后重置全局连接，避免跨测试串连
    mysql.reset_connection()
    yield
    mysql.reset_connection()


def test_get_connection_is_reused():
    c1 = mysql.get_connection()
    c2 = mysql.get_connection()
    assert c1 is c2


def test_execute_and_query_roundtrip(db_conn):
    new_id = mysql.execute(
        "INSERT INTO users (email, password, email_to, token) "
        "VALUES (%s, %s, %s, %s)",
        ("a@b.com", "hashed", "a@b.com", "tok123"),
    )
    assert isinstance(new_id, int) and new_id > 0

    rows = mysql.query("SELECT email, token FROM users WHERE id = %s", (new_id,))
    assert rows == [{"email": "a@b.com", "token": "tok123"}]


def test_query_returns_empty_list_when_no_rows(db_conn):
    rows = mysql.query("SELECT id FROM users WHERE email = %s", ("nope@x.com",))
    assert rows == []


def test_run_script_executes_multiple_statements(db_conn):
    mysql.run_script(
        "INSERT INTO rss_sources (name, url) VALUES ('s1', 'http://1');"
        "INSERT INTO rss_sources (name, url) VALUES ('s2', 'http://2');"
    )
    rows = mysql.query("SELECT name FROM rss_sources ORDER BY name")
    assert [r["name"] for r in rows] == ["s1", "s2"]
