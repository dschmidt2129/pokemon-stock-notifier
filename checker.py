import logging
import time
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class Checker:
    # buffer wait is not working when checking the page contents.  need to find different solution
    def __init__(self, user_agent=None, timeout=10, load_wait=5, buffer_wait=5):
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/115.0 Safari/537.36"
        )
        self.timeout = timeout
        self.load_wait = load_wait
        self.buffer_wait = buffer_wait

    def _button_is_visible(self, button):
        if button.has_attr("hidden"):
            return False

        style = button.get("style", "").lower().replace(" ", "")
        if "display:none" in style or "visibility:hidden" in style:
            return False

        button_classes = button.get("class", [])
        if any("hidden" in str(cls).lower() for cls in button_classes):
            return False

        return True

    def fetch(self, url):
        headers = {"User-Agent": self.user_agent}
        resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def is_in_stock(self, url):
        """Return (bool, reason_str). Uses simple heuristics for Target product pages.

        Heuristic summary:
        - If page contains 'sold out' or 'out of stock' -> not in stock
        - If page contains 'add to cart' button that is visible and not disabled -> in stock
        - Otherwise, return False with page snippet for debugging
        """
        html = self.fetch(url)
        logger.info("Page fetched for %s", url)
        if self.buffer_wait:
            logger.info(
                "Waiting %ss after fetch for page content to settle for %s",
                self.buffer_wait,
                url,
            )
            time.sleep(self.buffer_wait)
            logger.info(
                "Finished waiting %ss after fetch for %s",
                self.buffer_wait,
                url,
            )
        if self.load_wait:
            logger.info("Waiting %ss before checking page content for %s", self.load_wait, url)
            time.sleep(self.load_wait)
            logger.info("Finished waiting %ss, checking page content for %s", self.load_wait, url)
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ", strip=True).lower()

        # Check for explicit out of stock indicators first
        if any(kw in text for kw in ("sold out", "out of stock", "unavailable")):
            return False, "Found sold-out text"

        # Check for explicit in stock indicators
        if any(kw in text for kw in ("ship it", "available for pickup", "pick up")):
            return True, "Found availability text"

        # Fallback for pages that have stock text but no HTML button
        add_keywords = ("add to cart", "add to bag", "buy now")
        if not soup.find("button") and any(kw in text for kw in add_keywords):
            return True, "Found add-to-cart text"

        # Now check for add-to-cart buttons
        buttons = soup.find_all("button")
        logger.debug("Found %s total buttons on page", len(buttons))
        
        for idx, button in enumerate(buttons):
            btn_text = button.get_text(strip=True).lower()
            btn_id = button.get("id", "")
            btn_class = button.get("class", [])
            btn_disabled = button.has_attr("disabled")
            aria_disabled = button.get("aria-disabled", "").strip().lower() in ("true", "1")
            aria_label = button.get("aria-label", "").strip()
            data_test = button.get("data-test", "").strip()
            is_hidden = not self._button_is_visible(button)
            
            button_attrs = dict(button.attrs)
            
            logger.debug(
                "Button %s: text=%r, id=%r, data-test=%r, aria-label=%r, class=%s, disabled=%s, aria-disabled=%s, hidden=%s",
                idx,
                btn_text,
                btn_id,
                data_test,
                aria_label,
                btn_class,
                btn_disabled,
                aria_disabled,
                is_hidden,
            )
            logger.debug("Button attrs: %s", button_attrs)
            
            if any(kw in btn_text for kw in add_keywords) or "add to cart" in aria_label.lower():
                logger.debug("Matches add-to-cart keyword")
                
                if btn_disabled:
                    logger.debug("Has disabled attribute: SKIP")
                    continue
                if aria_disabled:
                    logger.debug("Has aria-disabled=true: SKIP")
                    continue
                if is_hidden:
                    logger.debug("Button is hidden or not visible: SKIP")
                    continue

                logger.debug("Button is ENABLED and VISIBLE: ITEM IS IN STOCK")
                return True, f"Found enabled add-to-cart button: {btn_text or aria_label}"
        
        logger.debug("No enabled add-to-cart button found")
        snippet = text[:200]
        return False, f"No clear stock indicators. Snippet: {snippet}"
