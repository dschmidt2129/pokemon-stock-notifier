import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError

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
    checker_attempt_timeout = cfg.get("checker_attempt_timeout_seconds", 45)
    checker = Checker(
        user_agent=cfg.get("user_agent"),
        load_wait=check_delay,
        attempt_timeout_seconds=checker_attempt_timeout,
    )
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
        # Cap each round so a hung Playwright session cannot block the loop forever.
        # Allow 15 s per product, minimum 90 s total.
        per_round_timeout = max(90, len(products) * 15)
        executor = ThreadPoolExecutor(max_workers=max_concurrent)
        futures = {}
        try:
            futures = {executor.submit(_check, p): p for p in products}
            try:
                for future in as_completed(futures, timeout=per_round_timeout):
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
            except FuturesTimeoutError:
                unfinished = sum(1 for future in futures if not future.done())
                logging.warning(
                    "Round timed out after %ss — %s product check(s) still running; skipping them",
                    per_round_timeout,
                    unfinished,
                )
        finally:
            # Do not block on shutdown when any worker is stuck in Playwright.
            # Running tasks cannot be force-cancelled in a thread pool, but this
            # keeps the outer loop responsive and lets the next round proceed.
            for future in futures:
                if not future.done():
                    future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

        time.sleep(interval)


if __name__ == "__main__":
    main()
