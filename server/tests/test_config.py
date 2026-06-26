import os
import pytest
from app.config import Settings, load_settings


def test_load_settings_reads_mysql_env(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "db.example.com")
    monkeypatch.setenv("MYSQL_PORT", "3307")
    monkeypatch.setenv("MYSQL_USER", "alice")
    monkeypatch.setenv("MYSQL_PASSWORD", "secret")
    monkeypatch.setenv("MYSQL_DATABASE", "pusher")

    s = load_settings()

    assert isinstance(s, Settings)
    assert s.mysql_host == "db.example.com"
    assert s.mysql_port == 3307
    assert s.mysql_user == "alice"
    assert s.mysql_password == "secret"
    assert s.mysql_database == "pusher"


def test_load_settings_defaults_for_optional(monkeypatch):
    for key in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
        monkeypatch.setenv(key, "x")
    # Clear every optional var so the test sees true defaults even when the
    # ambient env (e.g. a sourced deploy/.env) sets them.
    for key in ("MYSQL_PORT", "DEEPSEEK_MODEL", "PLANNER_MODEL",
                "ANALYST_MODEL", "REVIEWER_MODEL"):
        monkeypatch.delenv(key, raising=False)

    s = load_settings()

    assert s.mysql_port == 3306
    assert s.deepseek_model == "deepseek-chat"
    assert s.planner_model == "deepseek-r1"


def test_load_settings_missing_required_raises(monkeypatch):
    for key in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(RuntimeError):
        load_settings()


def test_timer_secret_optional(monkeypatch):
    for key in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
        monkeypatch.setenv(key, "x")
    monkeypatch.delenv("TIMER_SECRET", raising=False)
    assert load_settings().timer_secret == ""
