from app.db import mysql


def create_user(email, password_hash, email_to, token) -> int:
    return mysql.execute(
        "INSERT INTO users (email, password, email_to, token) "
        "VALUES (%s, %s, %s, %s)",
        (email, password_hash, email_to, token),
    )


def get_user_by_email(email):
    rows = mysql.query("SELECT * FROM users WHERE email = %s", (email,))
    return rows[0] if rows else None


def get_user_by_token(token):
    rows = mysql.query("SELECT * FROM users WHERE token = %s", (token,))
    return rows[0] if rows else None


def set_user_token(user_id, token) -> None:
    mysql.execute("UPDATE users SET token = %s WHERE id = %s", (token, user_id))
