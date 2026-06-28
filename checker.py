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

    def fetch(self, url):
        headers = {"User-Agent": self.user_agent}
        resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def get_target_cart_button(self, url):
        with sync_playwright() as p:
            # Use the system Chrome browser (channel="chrome") rather than Playwright's
            # bundled Chromium.  Target's bot-detection permanently blocks bundled Chromium;
            # real Chrome has the fingerprint needed to pass the challenge.
            browser = p.chromium.launch(
                channel="chrome",
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            
            # Emulate a standard desktop browser environment
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720}
            )
            # Remove the navigator.webdriver flag that headless Chrome exposes
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            )
            
            page = context.new_page()
            
            print(f"Navigating to: {url}")
            page.goto(url, wait_until="domcontentloaded")
            
            # Target's Add to Cart button relies on data attributes. 
            # We wait until the specific button test-ID or text renders.
            # Target also applies dynamic content loading, so we wait for the button to appear and is clickable 
            try:
                page.wait_for_selector('button[data-test="shippingButton"]', timeout=10000)
                logger.info("Add to cart button selector found on the page.")
            except Exception:
                print("Timeout waiting for the add to cart button element.")

            # Target shows a bot-detection challenge ("Loading screen / Almost there...")
            # inside a floating UI portal overlay before revealing the real page state.
            # On fast machines this overlay is still active when the click is attempted,
            # causing false results.  Wait for it to clear before proceeding.
            try:
                portal_text = page.evaluate("""
                    () => Array.from(document.querySelectorAll('[data-floating-ui-portal]'))
                              .map(p => p.textContent.trim().toLowerCase()).join(' ')
                """)
                bot_check_signals = ["loading screen", "almost there", "thank you for your patience", "loading content"]
                if any(s in portal_text for s in bot_check_signals):
                    logger.info("Target bot-check overlay detected; waiting for it to clear")
                    try:
                        page.wait_for_selector(".styles_overlay__AJMdo", state="hidden", timeout=8000)
                        logger.info("Bot-check overlay cleared")
                        # After the challenge clears, Target re-renders the page and makes stock
                        # API calls.  Wait for network idle so the button reaches its final state.
                        try:
                            page.wait_for_load_state("networkidle", timeout=10000)
                            logger.info("Network idle reached after bot-check — stock state is final")
                        except Exception:
                            logger.info("Network idle timeout after bot-check; proceeding")
                        # Re-wait for the shipping button in its final post-render state
                        try:
                            page.wait_for_selector('button[data-test="shippingButton"]', timeout=8000)
                            logger.info("Shipping button confirmed present after bot-check re-render")
                        except Exception:
                            logger.info("Shipping button not found after bot-check re-render; using current state")
                    except Exception as overlay_e:
                        logger.warning("Bot-check overlay did not clear (bot likely blocked request): %s", overlay_e)
                        browser.close()
                        return None, None
            except Exception as bot_e:
                logger.info("Bot-check overlay evaluation error: %s", bot_e)

            # Attempt to click the button using Playwright to determine enabled/disabled state
            selector = 'button[data-test="shippingButton"]'
            click_ok = False
            try:
                py_button = page.query_selector(selector)
                if py_button:
                    try:
                        page.click(selector, timeout=3000)
                        logger.info("Normal Playwright click succeeded — button appears enabled")
                        click_ok = True
                    except Exception as e:
                        err_text = str(e)
                        logger.info("Normal Playwright click failed: %s", err_text)
                        if "intercepts pointer events" in err_text or "intercepting pointer events" in err_text:
                            # The floating UI portal overlay is Target's mechanism for blocking
                            # the button (e.g. item sold out, not available for shipping).
                            # The button itself has no HTML `disabled` attribute regardless of
                            # stock state, so bypassing the overlay always produces a false
                            # positive.  Log the portal content for diagnostics, then treat
                            # a persistent overlay as "button unavailable".
                            portal_info = page.evaluate("""
                                () => Array.from(document.querySelectorAll('[data-floating-ui-portal]'))
                                          .map(p => ({ id: p.id, text: p.textContent.trim().substring(0, 300) }))
                            """)
                            logger.info("Floating UI portal(s) blocking button: %s", portal_info)
                            logger.info("Overlay persistently intercepts button after page load — treating button as unavailable")
                            click_ok = False
                        else:
                            logger.info("Click failed for a reason other than overlay interception; not using overlay fallback")
                            click_ok = False
                else:
                    logger.info("Playwright could not find button element for clicking")
            except Exception as e:
                logger.info("Error while attempting Playwright click check: %s", e)
            
            logger.info("Button Click Check Result: %s", "Enabled" if click_ok else "Disabled or Not Found")

            # Pass the fully rendered JavaScript page source to BeautifulSoup
            html_content = page.content()
            soup = BeautifulSoup(html_content, "html.parser")

            # Method A: Finding by Target's internal data-test attribute (Most Reliable)
            cart_button = soup.find("button", {"data-test": "shippingButton"})

            # Method B: Alternative fallback (if they are using standard fulfillment text)
            if not cart_button:
                cart_button = soup.find("button", string=lambda text: text and "Add to cart" in text)

            browser.close()
        return cart_button, click_ok

    def is_in_stock(self, url, max_retries=3, retry_delay=3):
        # Retry the full browser session on transient Playwright errors (e.g. "Target
        # crashed", "Target page closed").  Each retry recreates the browser from scratch.
        add_button, click_ok = None, False
        for attempt in range(1, max_retries + 1):
            try:
                add_button, click_ok = self.get_target_cart_button(url)
                if add_button is None and click_ok is None:
                    # Bot-check overlay was never cleared; retry after a delay
                    logger.warning(
                        "Bot-check blocked attempt %d/%d for %s; retrying in %ss…",
                        attempt, max_retries, url, retry_delay,
                    )
                    if attempt < max_retries:
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.error("All %d attempts blocked by bot-check for %s", max_retries, url)
                        return False, "Bot-check overlay blocked all attempts"
                break
            except Exception as exc:
                logger.warning(
                    "get_target_cart_button attempt %d/%d failed for %s: %s",
                    attempt, max_retries, url, exc,
                )
                if attempt < max_retries:
                    logger.info("Retrying in %ss…", retry_delay)
                    time.sleep(retry_delay)
                else:
                    logger.error("All %d attempts failed for %s", max_retries, url)
                    return False, f"Checker failed after {max_retries} attempts: {exc}"

        if add_button is not None:
            logger.info("Add-to-cart button found, checking visibility and enabled state")
            is_visible = self._button_is_visible(add_button)
            btn_text = add_button.get_text(strip=True).lower()
            aria_label = add_button.get("aria-label", "").strip()
            logger.info(
                "Found add-to-cart button: class=%s, id=%r, data-test=%r, disabled=%s, hidden=%s",
                add_button.get("class", []),
                add_button.get("id", ""),
                add_button.get("data-test", ""),
                click_ok, 
                is_visible
            )
            if not click_ok:
                logger.info("Add-to-cart button is disabled")
                return False, "Found add-to-cart button, but it is disabled"
            if not is_visible:
                logger.info("Add-to-cart button is hidden")
                return False, "Found add-to-cart button, but it is not visible"

            # If the Playwright click succeeded earlier, treat the button as enabled
            if click_ok:
                logger.info("Playwright click indicated the button is enabled: ITEM IS IN STOCK")
                return True, f"Found enabled add-to-cart button (click succeeded): {btn_text or aria_label}"

            logger.info("Add-to-cart button is enabled and visible: ITEM IS IN STOCK")
            return True, f"Found enabled add-to-cart button: {btn_text or aria_label}"

        logger.info("No add-to-cart button found")
        try:
            snippet = self.fetch(url)[:200]
        except Exception:
            snippet = ""
        return False, f"No clear stock indicators. Snippet: {snippet}"
