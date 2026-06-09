import time
import logging
import yaml

from target_checker import TargetChecker
from backends import notify_desktop, notify_webhook


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_config(path="config.yml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    cfg = load_config()
    url = cfg.get("product_url")
    interval = cfg.get("interval_seconds", 30)
    webhook = cfg.get("webhook_url")
    desktop = cfg.get("notify_desktop", True)

    checker = TargetChecker(user_agent=cfg.get("user_agent"))

    last_in_stock = False

    logging.info("Starting notifier for %s (every %ss)", url, interval)
    while True:
        try:
            in_stock, details = checker.is_in_stock(url)
            if in_stock and not last_in_stock:
                title = "Item In Stock"
                message = f"{details} -- {url}"
                logging.info("In stock! sending notifications")
                if desktop:
                    notify_desktop(title, message)
                if webhook:
                    notify_webhook(webhook, {"title": title, "message": message, "url": url})
            last_in_stock = in_stock
        except Exception as e:
            logging.exception("Error checking stock: %s", e)

        time.sleep(interval)


if __name__ == "__main__":
    main()
