import uuid
from app.db import mysql


def create_job(type_, user_id=None) -> str:
    job_id = str(uuid.uuid4())
    mysql.execute(
        "INSERT INTO jobs (id, user_id, type, status) VALUES (%s, %s, %s, 'pending')",
        (job_id, user_id, type_),
    )
    return job_id


def get_job(job_id):
    rows = mysql.query("SELECT * FROM jobs WHERE id = %s", (job_id,))
    return rows[0] if rows else None


def mark_running(job_id) -> None:
    mysql.execute("UPDATE jobs SET status = 'running' WHERE id = %s", (job_id,))


def mark_done(job_id, report_date) -> None:
    mysql.execute(
        "UPDATE jobs SET status = 'done', report_date = %s, finished_at = NOW() "
        "WHERE id = %s",
        (report_date, job_id),
    )


def mark_failed(job_id, error) -> None:
    mysql.execute(
        "UPDATE jobs SET status = 'failed', error = %s, finished_at = NOW() "
        "WHERE id = %s",
        (str(error), job_id),
    )
