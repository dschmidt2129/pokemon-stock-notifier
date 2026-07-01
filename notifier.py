import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from checker import Checker
from backends import notify_desktop, notify_webhook, notify_email
from config import build_product_list, load_config, validate_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    cfg = load_config()
    products = build_product_list(cfg)
    validate_config(cfg, products)
    interval = cfg.get("interval_seconds", 30)
    webhook = cfg.get("webhook_url")
    desktop = cfg.get("notify_desktop", True)
    email_cfg = cfg.get("email", {})
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

    def _check(product):
        try:
            in_stock, details = checker.is_in_stock(product["url"])
            return product, in_stock, details, None
        except Exception as exc:
            return product, False, "", exc

    max_concurrent = min(len(products), 4)
    while True:
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {executor.submit(_check, p): p for p in products}
            for future in as_completed(futures):
                product, in_stock, details, exc = future.result()
                url = product["url"]
                name = product["name"]

                if exc is not None:
                    logging.error("Error checking %s: %s", name, exc, exc_info=exc)
                    continue

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

        time.sleep(interval)


if __name__ == "__main__":
    main()
