from datetime import datetime, timezone, timedelta
from app.db import mysql

_BEIJING = timezone(timedelta(hours=8))


def beijing_today():
    return datetime.now(_BEIJING).date()


def save_report(user_id, report_date, content, news_summary,
                stock_summary, personal_analysis) -> int:
    return mysql.execute(
        "INSERT INTO reports "
        "(user_id, report_date, content, news_summary, stock_summary, personal_analysis) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (user_id, report_date, content, news_summary, stock_summary, personal_analysis),
    )


def get_report(user_id, report_date):
    rows = mysql.query(
        "SELECT * FROM reports WHERE user_id = %s AND report_date = %s "
        "ORDER BY id DESC LIMIT 1",
        (user_id, report_date),
    )
    return rows[0] if rows else None


def get_today_report(user_id):
    return get_report(user_id, beijing_today())


def list_report_dates(user_id) -> list[str]:
    rows = mysql.query(
        "SELECT DISTINCT report_date FROM reports WHERE user_id = %s "
        "ORDER BY report_date DESC",
        (user_id,),
    )
    return [r["report_date"].strftime("%Y-%m-%d") for r in rows]
