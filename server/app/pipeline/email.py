import smtplib
from email.message import EmailMessage
from app.config import load_settings


def build_message(from_addr, to_addr, subject, html) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(html, subtype="html")
    return msg


def send_report_email(to_addr, subject, html, smtp_factory=None) -> None:
    s = load_settings()
    factory = smtp_factory or smtplib.SMTP
    msg = build_message(s.email_from, to_addr, subject, html)
    with factory(s.email_smtp_host, s.email_smtp_port) as client:
        client.starttls()
        client.login(s.email_from, s.email_password)
        client.send_message(msg)
