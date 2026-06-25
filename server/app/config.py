import os
from dataclasses import dataclass

_REQUIRED = ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE")


@dataclass
class Settings:
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str
    deepseek_api_key: str
    deepseek_model: str
    planner_model: str
    email_smtp_host: str
    email_smtp_port: int
    email_from: str
    email_password: str


def load_settings() -> Settings:
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"missing required env vars: {', '.join(missing)}")

    return Settings(
        mysql_host=os.environ["MYSQL_HOST"],
        mysql_port=int(os.environ.get("MYSQL_PORT", "3306")),
        mysql_user=os.environ["MYSQL_USER"],
        mysql_password=os.environ["MYSQL_PASSWORD"],
        mysql_database=os.environ["MYSQL_DATABASE"],
        deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        deepseek_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        planner_model=os.environ.get("PLANNER_MODEL", "deepseek-r1"),
        email_smtp_host=os.environ.get("EMAIL_SMTP_HOST", ""),
        email_smtp_port=int(os.environ.get("EMAIL_SMTP_PORT", "587")),
        email_from=os.environ.get("EMAIL_FROM", ""),
        email_password=os.environ.get("EMAIL_PASSWORD", ""),
    )
