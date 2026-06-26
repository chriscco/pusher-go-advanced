import os
import pathlib
import pymysql
import pytest

SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[2] / "sql" / "schema.sql"


def pytest_configure(config):
    """Refuse to run against a non-test database.

    The ``db_conn`` fixture wipes every table before each test, so pointing
    MYSQL_DATABASE at a real database (e.g. via ``source deploy/.env``) would
    destroy production data. Require a name ending in ``_test`` unless the
    operator explicitly opts out with ALLOW_NONTEST_DB=1.
    """
    db = os.environ.get("MYSQL_DATABASE", "pusher_test")
    if not db.endswith("_test") and os.environ.get("ALLOW_NONTEST_DB") != "1":
        raise pytest.UsageError(
            f"refusing to run the test suite against database {db!r}: it DELETEs "
            f"all rows from every table before each test. Use a database whose "
            f"name ends with '_test' (e.g. pusher_test), or set ALLOW_NONTEST_DB=1 "
            f"to override. Never point MYSQL_DATABASE at the production database."
        )

# 删除顺序：先删有外键依赖的子表，再删父表
_TABLES_IN_DELETE_ORDER = [
    "reports",
    "portfolios",
    "fund_holdings",
    "rss_sources",
    "jobs",
    "users",
]


def _connect():
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", "root"),
        database=os.environ.get("MYSQL_DATABASE", "pusher_test"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def _apply_schema(conn):
    ddl = SCHEMA_PATH.read_text(encoding="utf-8")
    statements = [s.strip() for s in ddl.split(";") if s.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)


@pytest.fixture
def db_conn():
    conn = _connect()
    _apply_schema(conn)
    # 每个测试开始前清空数据，保证隔离
    with conn.cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        for table in _TABLES_IN_DELETE_ORDER:
            cur.execute(f"DELETE FROM {table}")
        cur.execute("SET FOREIGN_KEY_CHECKS=1")
    yield conn
    conn.close()
