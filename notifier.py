import asyncio
import logging
import time

from checker import Checker, StockStatus
from backends import notify_desktop, notify_webhook, notify_email
from config import build_product_list, load_config, validate_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def main():
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
    browser_concurrency = cfg.get("browser_concurrency", 2)
    checker = Checker(
        user_agent=cfg.get("user_agent"),
        load_wait=check_delay,
        attempt_timeout_seconds=checker_attempt_timeout,
        browser_concurrency=browser_concurrency,
    )
    last_in_stock = {product["url"]: False for product in products}
    last_notification_time = {product["url"]: 0.0 for product in products}

    logging.info("Starting notifier for %s products (every %ss)", len(products), interval)
    for product in products:
        logging.info(" - %s: %s", product["name"], product["url"])

    max_concurrent = min(len(products), browser_concurrency)
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _check(product):
        async with semaphore:
            try:
                result = await checker.check(product["url"])
                return product, result, None
            except Exception as exc:
                return product, None, exc

    try:
        while True:
            # Cap each round so a hung check cannot block the loop forever. Unlike threads,
            # asyncio tasks can be cancelled cleanly at their next await point on timeout.
            per_round_timeout = max(90, len(products) * 15)
            tasks = [asyncio.create_task(_check(p)) for p in products]
            try:
                done, pending = await asyncio.wait(tasks, timeout=per_round_timeout)
                if pending:
                    logging.warning(
                        "Round timed out after %ss — %s product check(s) still running; cancelling them",
                        per_round_timeout,
                        len(pending),
                    )
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)

                for task in done:
                    product, result, exc = task.result()
                    url = product["url"]
                    name = product["name"]

                    if exc is not None:
                        logging.error("Error checking %s: %s", name, exc, exc_info=exc)
                        continue

                    logging.info(
                        "checking stock for item: %s url=%s - status=%s, details=%s",
                        name,
                        url,
                        result.status.value,
                        result.details,
                    )
                    now = time.time()

                    should_notify = False
                    if result.status is StockStatus.IN_STOCK:
                        if not last_in_stock[url]:
                            should_notify = True
                        elif cooldown_seconds and now - last_notification_time[url] >= cooldown_seconds:
                            should_notify = True

                    if should_notify:
                        title = f"{name} In Stock"
                        message = f"{result.details} -- {url}"
                        logging.info("In stock! %s", title)
                        if desktop:
                            await asyncio.to_thread(notify_desktop, title, message)
                        if webhook:
                            await asyncio.to_thread(
                                notify_webhook,
                                webhook,
                                {"title": title, "message": message, "url": url, "product": name},
                            )
                        if email_enabled:
                            body = email_cfg.get("body", "")
                            if body:
                                body = body.format(product_name=name, url=url)
                            await asyncio.to_thread(notify_email, email_cfg, title, message, body)
                        last_notification_time[url] = now

                    if result.status in (StockStatus.IN_STOCK, StockStatus.OUT_OF_STOCK):
                        last_in_stock[url] = result.status is StockStatus.IN_STOCK
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()

            await asyncio.sleep(interval)
    finally:
        await checker.aclose()


if __name__ == "__main__":
    asyncio.run(main())
