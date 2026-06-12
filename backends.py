import logging
import requests
import smtplib
from email.message import EmailMessage


def notify_desktop(title, message):
    try:
        from plyer import notification

        notification.notify(title=title, message=message, timeout=10)
    except Exception:
        logging.exception("Desktop notification failed, falling back to console")
        print(f"NOTIFICATION: {title} - {message}")


def notify_webhook(url, payload):
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
    except Exception:
        logging.exception("Webhook notification failed")


def notify_email(email_cfg, title, message):
    try:
        smtp_server = email_cfg.get("smtp_server")
        smtp_port = int(email_cfg.get("smtp_port", 587))
        username = email_cfg.get("username")
        password = email_cfg.get("password")
        from_addr = email_cfg.get("from")
        to_addrs = email_cfg.get("to")
        subject_prefix = email_cfg.get("subject_prefix", "")
        use_tls = email_cfg.get("use_tls", True)
        use_ssl = email_cfg.get("use_ssl", False)

        if not smtp_server or not from_addr or not to_addrs:
            logging.warning("Email notification skipped because email config is incomplete")
            return

        if isinstance(to_addrs, str):
            to_addrs = [addr.strip() for addr in to_addrs.split(",") if addr.strip()]

        email_message = EmailMessage()
        email_message["Subject"] = f"{subject_prefix} {title}".strip()
        email_message["From"] = from_addr
        email_message["To"] = ", ".join(to_addrs)
        email_message.set_content(message)

        if use_ssl or smtp_port == 465:
            smtp = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10)
        else:
            smtp = smtplib.SMTP(smtp_server, smtp_port, timeout=10)

        with smtp as server:
            if not use_ssl and use_tls:
                server.starttls()
            if username and password:
                server.login(username, password)
            server.send_message(email_message)

        logging.info("Email notification sent to %s", to_addrs)
    except Exception:
        logging.exception("Email notification failed")
