import pymysql
from app.config import load_settings

_conn = None


def get_connection():
    global _conn
    if _conn is None or not _conn.open:
        s = load_settings()
        _conn = pymysql.connect(
            host=s.mysql_host,
            port=s.mysql_port,
            user=s.mysql_user,
            password=s.mysql_password,
            database=s.mysql_database,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
    _conn.ping(reconnect=True)
    return _conn


def query(sql, params=None):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())


def execute(sql, params=None):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        conn.commit()
        return cur.lastrowid


def run_script(sql_text):
    conn = get_connection()
    statements = [s.strip() for s in sql_text.split(";") if s.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
    conn.commit()


def reset_connection():
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _conn = None
