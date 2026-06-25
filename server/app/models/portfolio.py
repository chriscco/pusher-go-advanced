from app.db import mysql


def add_portfolio(user_id, symbol, name, type_, market, quantity, cost_price) -> int:
    return mysql.execute(
        "INSERT INTO portfolios "
        "(user_id, symbol, name, type, market, quantity, cost_price) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (user_id, symbol, name, type_, market, quantity, cost_price),
    )


def list_portfolios(user_id):
    return mysql.query(
        "SELECT * FROM portfolios WHERE user_id = %s ORDER BY id", (user_id,)
    )


def get_portfolio(portfolio_id):
    rows = mysql.query("SELECT * FROM portfolios WHERE id = %s", (portfolio_id,))
    return rows[0] if rows else None


def delete_portfolio(portfolio_id, user_id) -> bool:
    conn = mysql.get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM portfolios WHERE id = %s AND user_id = %s",
            (portfolio_id, user_id),
        )
        cur.execute("SELECT ROW_COUNT() AS n")
        rowcount = int(cur.fetchone()["n"])
    conn.commit()
    return rowcount > 0
