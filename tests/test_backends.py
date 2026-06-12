from unittest.mock import MagicMock, patch

from backends import notify_email


def test_notify_email_skips_incomplete_config():
    cfg = {"smtp_server": "", "from": "", "to": ""}
    with patch("backends.smtplib.SMTP") as smtp_cls:
        notify_email(cfg, "Title", "Message")
        smtp_cls.assert_not_called()


def test_notify_email_uses_tls_and_sends_message():
    cfg = {
        "smtp_server": "smtp.example.com",
        "smtp_port": 587,
        "username": "user",
        "password": "pass",
        "from": "sender@example.com",
        "to": "recipient@example.com",
        "use_tls": True,
        "use_ssl": False,
    }

    mock_smtp = MagicMock()
    mock_context = MagicMock(__enter__=MagicMock(return_value=mock_smtp), __exit__=MagicMock(return_value=None))

    with patch("backends.smtplib.SMTP", return_value=mock_context) as smtp_cls, patch("backends.smtplib.SMTP_SSL") as ssl_cls:
        notify_email(cfg, "Stock Alert", "Item is in stock")

    smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=10)
    ssl_cls.assert_not_called()
    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once_with("user", "pass")
    mock_smtp.send_message.assert_called_once()


def test_notify_email_uses_ssl_when_requested():
    cfg = {
        "smtp_server": "smtp.example.com",
        "smtp_port": 465,
        "from": "sender@example.com",
        "to": "recipient@example.com",
        "use_tls": False,
        "use_ssl": True,
    }

    mock_smtp = MagicMock()
    mock_context = MagicMock(__enter__=MagicMock(return_value=mock_smtp), __exit__=MagicMock(return_value=None))

    with patch("backends.smtplib.SMTP_SSL", return_value=mock_context) as ssl_cls:
        notify_email(cfg, "Stock Alert", "Item is in stock")

    ssl_cls.assert_called_once_with("smtp.example.com", 465, timeout=10)
    mock_smtp.send_message.assert_called_once()
