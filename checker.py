import logging
import time
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)


class Checker:
    # buffer wait is not working when checking the page contents.  need to find different solution
    def __init__(self, user_agent=None, timeout=10, load_wait=0, buffer_wait=5):
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

    def get_target_cart_button(self, url):
        with sync_playwright() as p:
            # Launch browser with basic user arguments to limit bot detection
            browser = p.chromium.launch(headless=True)
            
            # Emulate a standard desktop browser environment
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720}
            )
            
            page = context.new_page()
            
            print(f"Navigating to: {url}")
            page.goto(url, wait_until="domcontentloaded")
            
            # Target's Add to Cart button relies on data attributes. 
            # We wait until the specific button test-ID or text renders.
            try:
                page.wait_for_selector('button[data-test="shippingButton"]', timeout=10000)
            except Exception:
                print("Timeout waiting for the add to cart button element.")

            # Pass the fully rendered JavaScript page source to BeautifulSoup
            html_content = page.content()
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Method A: Finding by Target's internal data-test attribute (Most Reliable)
            cart_button = soup.find("button", {"data-test": "shippingButton"})
            
            # Method B: Alternative fallback (if they are using standard fulfillment text)
            if not cart_button:
                cart_button = soup.find("button", string=lambda text: text and "Add to cart" in text)

            if cart_button:
                print("--- Button Found Successfully! ---")
                print(f"Tag: {cart_button.name}")
                print(f"Text Content: {cart_button.get_text(strip=True)}")
                print(f"Attributes: {cart_button.attrs}")
            else:
                print("Could not locate the button in the rendered HTML structural tree.")
                
            browser.close()

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
        # add_keywords = ("add to cart", "add to bag", "buy now")
        # if not soup.find("button") and any(kw in text for kw in add_keywords):
        #     return True, "Found add-to-cart text"

        # Now check for the add-to-cart button specifically
        add_button = self.get_target_cart_button(url)
        if add_button is not None:
            btn_text = add_button.get_text(strip=True).lower()
            aria_label = add_button.get("aria-label", "").strip()
            is_hidden = not self._button_is_visible(add_button)
            is_disabled = self._button_is_disabled(add_button)

            logger.debug(
                "Found add-to-cart button: text=%r, aria-label=%r, class=%s, id=%r, data-test=%r, disabled=%s, hidden=%s",
                btn_text,
                aria_label,
                add_button.get("class", []),
                add_button.get("id", ""),
                add_button.get("data-test", ""),
                is_disabled,
                is_hidden,
            )

            if is_disabled:
                logger.info("Add-to-cart button is disabled")
                return False, "Found add-to-cart button, but it is disabled"
            if is_hidden:
                logger.info("Add-to-cart button is hidden")
                return False, "Found add-to-cart button, but it is not visible"

            logger.info("Add-to-cart button is enabled and visible: ITEM IS IN STOCK")
            return True, f"Found enabled add-to-cart button: {btn_text or aria_label}"

        logger.info("No add-to-cart button found")
        snippet = text[:200]
        return False, f"No clear stock indicators. Snippet: {snippet}"
