import time
import logging
import yaml

from checker import Checker
from backends import notify_desktop, notify_webhook


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


def main():
    cfg = load_config()
    products = build_product_list(cfg)
    interval = cfg.get("interval_seconds", 30)
    webhook = cfg.get("webhook_url")
    desktop = cfg.get("notify_desktop", True)

    if not products:
        raise ValueError("No products configured in config.yml")

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
                logging.info("checking stock for items: %s",name)
                if in_stock and not last_in_stock[url]:
                    title = f"{name} In Stock"
                    message = f"{details} -- {url}"
                    logging.info("In stock! %s", title)
                    if desktop:
                        notify_desktop(title, message)
                    if webhook:
                        notify_webhook(webhook, {"title": title, "message": message, "url": url, "product": name})
                last_in_stock[url] = in_stock
            except Exception as e:
                logging.exception("Error checking %s: %s", url, e)

        time.sleep(interval)


if __name__ == "__main__":
    main()
