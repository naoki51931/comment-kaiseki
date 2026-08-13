import pytest

from app.config import settings
from app.services.email import send_verification_email


class FakeSmtp:
    instance: "FakeSmtp | None" = None

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.calls: list[object] = []
        FakeSmtp.instance = self

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def ehlo(self) -> None:
        self.calls.append("ehlo")

    def starttls(self) -> None:
        self.calls.append("starttls")

    def login(self, username: str, password: str) -> None:
        self.calls.append(("login", username, password))

    def send_message(self, message: object) -> None:
        self.calls.append(("send", message))


def test_gmail_starttls_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "email_delivery_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_from", "sender@example.test")
    monkeypatch.setattr(settings, "smtp_username", "sender@example.test")
    monkeypatch.setattr(settings, "smtp_password", "app-password")
    monkeypatch.setattr(settings, "smtp_starttls", True)
    monkeypatch.setattr(settings, "smtp_ssl", False)
    monkeypatch.setattr("app.services.email.smtplib.SMTP", FakeSmtp)

    send_verification_email("recipient@example.test", "https://example.test/verify")

    smtp = FakeSmtp.instance
    assert smtp is not None
    assert (smtp.host, smtp.port) == ("smtp.gmail.com", 587)
    assert smtp.calls[:4] == ["ehlo", "starttls", "ehlo", ("login", "sender@example.test", "app-password")]
    assert smtp.calls[4][0] == "send"
