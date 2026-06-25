import pytest
from app.pipeline import email as email_mod


def test_build_message_sets_headers_and_html():
    msg = email_mod.build_message("from@x.com", "to@y.com", "标题", "<h1>hi</h1>")
    assert msg["From"] == "from@x.com"
    assert msg["To"] == "to@y.com"
    assert msg["Subject"] == "标题"
    assert msg.get_content_type() == "text/html"
    assert "<h1>hi</h1>" in msg.get_content()


def test_send_report_email_uses_smtp(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "x")
    monkeypatch.setenv("MYSQL_USER", "x")
    monkeypatch.setenv("MYSQL_PASSWORD", "x")
    monkeypatch.setenv("MYSQL_DATABASE", "x")
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.test")
    monkeypatch.setenv("EMAIL_SMTP_PORT", "587")
    monkeypatch.setenv("EMAIL_FROM", "from@x.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")

    events = []

    class FakeSMTP:
        def __init__(self, host, port):
            events.append(("init", host, port))
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def starttls(self):
            events.append(("starttls",))
        def login(self, user, pw):
            events.append(("login", user, pw))
        def send_message(self, msg):
            events.append(("send", msg["To"]))

    email_mod.send_report_email("to@y.com", "主题", "<p>x</p>", smtp_factory=FakeSMTP)

    assert ("init", "smtp.test", 587) in events
    assert ("starttls",) in events
    assert ("login", "from@x.com", "secret") in events
    assert ("send", "to@y.com") in events


def test_send_report_email_propagates_failure(monkeypatch):
    for k in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("EMAIL_FROM", "from@x.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")

    class BoomSMTP:
        def __init__(self, *a):
            raise RuntimeError("smtp down")

    with pytest.raises(RuntimeError):
        email_mod.send_report_email("to@y.com", "s", "<p>x</p>", smtp_factory=BoomSMTP)
