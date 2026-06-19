import logging
import time
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page

logger = logging.getLogger(__name__)


class Checker:
    # buffer wait is not working when checking the page contents.  need to find different solution
    def __init__(self, user_agent=None, timeout=10, load_wait=0, buffer_wait=0):
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/115.0 Safari/537.36"
        )
        self.timeout = timeout
        self.load_wait = load_wait
        self.buffer_wait = buffer_wait

    def _button_is_visible(self, button):
        logger.info("Checking button visibility")
        if button.has_attr("hidden"):
            logger.info("Button is hidden due to 'hidden' attribute")
            return False
        logger.info("Button does not have 'hidden' attribute, assuming it is visible")
        return True

    def _button_is_disabled(self, button):
        logger.info("Checking button accessibility")
        if button.has_attr("disabled"):
            logger.info("Button is disabled due to 'disabled' attribute")
            return True
        logger.info("Button does not have 'disabled' attribute, assuming it is enabled  and accessible")
        return False

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
                logger.info("Add to cart button selector found on the page.")
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
        return cart_button

    def is_in_stock(self, url):

        # Now check for the add-to-cart button specifically
        add_button = self.get_target_cart_button(url)
        
        if add_button is not None:
            logger.info("Add-to-cart button found, checking visibility and enabled state")
            logger.info(f"Button attributes: {add_button.attrs}")
            is_visible = self._button_is_visible(add_button)
            is_disabled = self._button_is_disabled(add_button)
            btn_text = add_button.get_text(strip=True).lower()
            aria_label = add_button.get("aria-label", "").strip()
            logger.info(
                "Found add-to-cart button: class=%s, id=%r, data-test=%r, disabled=%s, hidden=%s",
                add_button.get("class", []),
                add_button.get("id", ""),
                add_button.get("data-test", ""),
                add_button.get("disabled", ""),  
                is_visible
            )
            if is_disabled:
                logger.info("Add-to-cart button is disabled")
                return False, "Found add-to-cart button, but it is disabled"
            if not is_visible:
                logger.info("Add-to-cart button is hidden")
                return False, "Found add-to-cart button, but it is not visible"

            logger.info("Add-to-cart button is enabled and visible: ITEM IS IN STOCK")
            return True, f"Found enabled add-to-cart button: {btn_text or aria_label}"

        logger.info("No add-to-cart button found")
        snippet = text[:200]
        return False, f"No clear stock indicators. Snippet: {snippet}"
