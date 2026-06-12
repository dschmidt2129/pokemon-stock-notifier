import time
import logging
import yaml

from checker import Checker
from backends import notify_desktop, notify_webhook, notify_email


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_config(path="config.yml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_product_list(cfg):
    products = cfg.get("products")
    if products:
        return [
            {
                "name": product.get("name") or product.get("url"),
                "url": product["url"],
            }
            for product in products
            if product.get("url")
        ]

    # Backwards compatibility for old single-product config keys.
    fallback = []
    for key, value in cfg.items():
        if key.endswith("_url") and isinstance(value, str):
            fallback.append({"name": key, "url": value})

    return fallback


def validate_config(cfg, products):
    if not products:
        raise ValueError("No products configured in config.yml")

    for product in products:
        if not product.get("url"):
            raise ValueError(f"Product entry missing 'url': {product}")

    if cfg.get("interval_seconds") is not None:
        interval = cfg["interval_seconds"]
        if not isinstance(interval, int) or interval <= 0:
            raise ValueError("interval_seconds must be a positive integer")

    email_cfg = cfg.get("email")
    if email_cfg is None:
        return

    if not isinstance(email_cfg, dict):
        raise ValueError("The 'email' config section must be a mapping")

    if any(value for value in email_cfg.values() if value is not None):
        missing = [
            field
            for field in ("smtp_server", "from", "to")
            if not email_cfg.get(field)
        ]
        if missing:
            raise ValueError(
                "Email config is incomplete. Add the following fields: "
                + ", ".join(missing)
            )


def main():
    cfg = load_config()
    products = build_product_list(cfg)
    validate_config(cfg, products)
    interval = cfg.get("interval_seconds", 30)
    webhook = cfg.get("webhook_url")
    desktop = cfg.get("notify_desktop", True)
    email_cfg = cfg.get("email", {})

    checker = Checker(user_agent=cfg.get("user_agent"))
    last_in_stock = {product["url"]: False for product in products}

    logging.info("Starting notifier for %s products (every %ss)", len(products), interval)
    for product in products:
        logging.info(" - %s: %s", product["name"], product["url"])

    while True:
        for product in products:
            url = product["url"]
            name = product["name"]
            try:
                in_stock, details = checker.is_in_stock(url)
                logging.info("checking stock for item: %s", name)
                if in_stock and not last_in_stock[url]:
                    title = f"{name} In Stock"
                    message = f"{details} -- {url}"
                    logging.info("In stock! %s", title)
                    if desktop:
                        notify_desktop(title, message)
                    if webhook:
                        notify_webhook(webhook, {"title": title, "message": message, "url": url, "product": name})
                    if email_cfg:
                        body = email_cfg.get("body", "")
                        if body:
                            body = body.format(product_name=name, url=url)
                        notify_email(email_cfg, title, message, body)
                last_in_stock[url] = in_stock
            except Exception as e:
                logging.exception("Error checking %s: %s", url, e)

        time.sleep(interval)


if __name__ == "__main__":
    main()
