import requests
from bs4 import BeautifulSoup


class TargetChecker:
    def __init__(self, user_agent=None, timeout=10):
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/115.0 Safari/537.36"
        )
        self.timeout = timeout

    def fetch(self, url):
        headers = {"User-Agent": self.user_agent}
        resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def is_in_stock(self, url):
        """Return (bool, reason_str). Uses simple heuristics for Target product pages.

        Heuristic summary:
        - If page contains phrases like 'add to cart' or 'add to bag' -> in stock
        - If page contains 'sold out' or 'out of stock' -> not in stock
        - Otherwise, return False with page snippet for debugging
        """
        html = self.fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ", strip=True).lower()

        if any(kw in text for kw in ("add to cart", "add to bag", "add to cart button", "add to cart\"")):
            return True, "Found add-to-cart text"

        if any(kw in text for kw in ("sold out", "out of stock", "unavailable")):
            return False, "Found sold-out text"

        # Some Target pages show 'Ship it' or 'Available for pickup' when available
        if any(kw in text for kw in ("ship it", "available for pickup", "pick up")):
            return True, "Found availability text"

        # fallback: check for presence of a button element that looks like add-to-cart
        button = soup.find("button")
        if button and button.get_text(strip=True):
            btn_text = button.get_text(strip=True).lower()
            if "add" in btn_text and ("cart" in btn_text or "bag" in btn_text):
                return True, f"Found button text: {btn_text}"

        # otherwise return False and a short snippet for inspection
        snippet = text[:200]
        return False, f"No clear stock indicators. Snippet: {snippet}"
