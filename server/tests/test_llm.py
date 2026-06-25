import pytest
from app.agents import llm


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")


def test_chat_returns_first_message():
    captured = {}

    def poster(url, headers, payload):
        captured["url"] = url
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "hello world"}}]}

    out = llm.chat([{"role": "user", "content": "hi"}], "deepseek-chat", poster=poster)
    assert out == "hello world"
    assert captured["url"].endswith("/chat/completions")
    assert captured["payload"]["model"] == "deepseek-chat"


def test_resolve_uses_env_default_when_no_user_key():
    cfg = llm.resolve_model_config({"model_key": None})
    assert cfg["api_key"] == "env-key"


def test_resolve_uses_user_key_when_present():
    cfg = llm.resolve_model_config(
        {"model_key": "user-key", "model_endpoint": "https://my.endpoint"}
    )
    assert cfg["api_key"] == "user-key"
    assert cfg["endpoint"] == "https://my.endpoint"
