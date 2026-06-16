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

    if cfg.get("stock_notification_cooldown_minutes") is not None:
        cooldown = cfg["stock_notification_cooldown_minutes"]
        if not isinstance(cooldown, int) or cooldown < 0:
            raise ValueError(
                "stock_notification_cooldown_minutes must be a non-negative integer"
            )

    if cfg.get("check_delay_seconds") is not None:
        delay = cfg["check_delay_seconds"]
        if not isinstance(delay, int) or delay < 0:
            raise ValueError("check_delay_seconds must be a non-negative integer")

    email_cfg = cfg.get("email")
    if email_cfg is None:
        return

    if not isinstance(email_cfg, dict):
        raise ValueError("The 'email' config section must be a mapping")

    # Treat email as "enabled" only when the user has provided at least one
    # meaningful email field (e.g. smtp_server, username, from, to). Defaults
    # like smtp_port/use_tls alone should not enable email validation.
    enabled_keys = ("smtp_server", "username", "password", "from", "to")
    enabled = any(bool(email_cfg.get(k)) for k in enabled_keys)
    if not enabled:
        return

    missing = [field for field in ("smtp_server", "from", "to") if not email_cfg.get(field)]
    if missing:
        raise ValueError(
            "Email config is incomplete. Add the following fields: " + ", ".join(missing)
        )


def main():
    cfg = load_config()
    products = build_product_list(cfg)
    validate_config(cfg, products)
    interval = cfg.get("interval_seconds", 30)
    webhook = cfg.get("webhook_url")
    desktop = cfg.get("notify_desktop", True)
    email_cfg = cfg.get("email", {})
    # Only consider email sending enabled when essential fields are provided.
    email_enabled = bool(email_cfg and any(email_cfg.get(k) for k in ("smtp_server", "from", "to")))

    cooldown_minutes = cfg.get("stock_notification_cooldown_minutes", 5)
    cooldown_seconds = cooldown_minutes * 60
    check_delay = cfg.get("check_delay_seconds", 5)
    checker = Checker(user_agent=cfg.get("user_agent"), load_wait=check_delay)
    last_in_stock = {product["url"]: False for product in products}
    last_notification_time = {product["url"]: 0.0 for product in products}

    logging.info("Starting notifier for %s products (every %ss)", len(products), interval)
    for product in products:
        logging.info(" - %s: %s", product["name"], product["url"])

    while True:
        for product in products:
            url = product["url"]
            name = product["name"]
            try:
                in_stock, details = checker.is_in_stock(url)
                logging.info(
                    "checking stock for item: %s url=%s - in_stock=%s, details=%s",
                    name,
                    url,
                    in_stock,
                    details,
                )
                now = time.time()

                should_notify = False
                if in_stock:
                    if not last_in_stock[url]:
                        should_notify = True
                    elif cooldown_seconds and now - last_notification_time[url] >= cooldown_seconds:
                        should_notify = True

                if should_notify:
                    title = f"{name} In Stock"
                    message = f"{details} -- {url}"
                    logging.info("In stock! %s", title)
                    if desktop:
                        notify_desktop(title, message)
                    if webhook:
                        notify_webhook(webhook, {"title": title, "message": message, "url": url, "product": name})
                    if email_enabled:
                        body = email_cfg.get("body", "")
                        if body:
                            body = body.format(product_name=name, url=url)
                        notify_email(email_cfg, title, message, body)
                    last_notification_time[url] = now

                last_in_stock[url] = in_stock
            except Exception as e:
                logging.exception("Error checking %s: %s", url, e)

        time.sleep(interval)


if __name__ == "__main__":
    main()
