import logging
import requests


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
