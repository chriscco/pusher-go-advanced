import pytest
from app.db import mysql
from app.models import user, portfolio


@pytest.fixture(autouse=True)
def _reset(db_conn):
    mysql.reset_connection()
    yield
    mysql.reset_connection()


@pytest.fixture
def uid():
    return user.create_user("p@x.com", "h", "p@x.com", "tok")


def test_add_and_list(uid):
    pid = portfolio.add_portfolio(uid, "600519", "贵州茅台", "stock", "cn", 100, 1500.0)
    assert isinstance(pid, int) and pid > 0

    rows = portfolio.list_portfolios(uid)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "600519"
    assert rows[0]["market"] == "cn"
    assert float(rows[0]["quantity"]) == 100.0


def test_add_optional_fields_null(uid):
    pid = portfolio.add_portfolio(uid, "AAPL", None, "stock", "us", None, None)
    row = portfolio.get_portfolio(pid)
    assert row["quantity"] is None
    assert row["cost_price"] is None
    assert row["market"] == "us"


def test_delete_own(uid):
    pid = portfolio.add_portfolio(uid, "600519", None, "stock", "cn", None, None)
    assert portfolio.delete_portfolio(pid, uid) is True
    assert portfolio.get_portfolio(pid) is None


def test_delete_other_users_fails(uid):
    other = user.create_user("o@x.com", "h", "o@x.com", "tok2")
    pid = portfolio.add_portfolio(uid, "600519", None, "stock", "cn", None, None)
    assert portfolio.delete_portfolio(pid, other) is False
    assert portfolio.get_portfolio(pid) is not None
