EXPECTED_TABLES = {
    "users",
    "portfolios",
    "fund_holdings",
    "reports",
    "rss_sources",
    "jobs",
}


def test_all_tables_created(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        rows = cur.fetchall()
    # DictCursor 下每行是 {'Tables_in_<db>': name}
    names = {list(r.values())[0] for r in rows}
    assert EXPECTED_TABLES.issubset(names)


def test_portfolios_has_market_column(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM portfolios LIKE 'market'")
        col = cur.fetchone()
    assert col is not None
    assert "enum('cn','hk','us')" in col["Type"].lower()


def test_portfolios_quantity_nullable(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM portfolios LIKE 'quantity'")
        col = cur.fetchone()
    assert col is not None
    assert col["Null"] == "YES"


def test_jobs_status_default_pending(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM jobs LIKE 'status'")
        col = cur.fetchone()
    assert col is not None
    assert col["Default"] == "pending"
