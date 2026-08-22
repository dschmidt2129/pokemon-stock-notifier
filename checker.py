import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from queue import Empty, Queue
from urllib.parse import urlparse
import requests
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# Candidate selectors in priority order.
# Target occasionally renames these; extend the list if a new attribute is discovered.
_CART_BUTTON_DATA_TESTS = [
    "shippingButton",
    "addToCartButton",
    "orderPickupButton",
    "fulfillmentAddToCartButton",
]
_CART_BUTTON_SELECTORS = [f'button[data-test="{dt}"]' for dt in _CART_BUTTON_DATA_TESTS]
_CART_BUTTON_COMBINED = ", ".join(_CART_BUTTON_SELECTORS)
_WALMART_CART_BUTTON_SELECTORS = [
    'button[data-automation-id="add-to-cart"]',
    'button[data-automation-id="atc-button"]',
    'button[data-automation-id="shippingButton"]',
    'button[data-testid*="add-to-cart" i]',
    'button[aria-label*="add to cart" i]',
]

_OUT_OF_STOCK_TERMS = [
    "alternative",
    "alternatives",
    "sold out",
    "out of stock",
    "check stores",
    "check nearby stores",
    "notify me",
    "see similar",
    "currently out of stock",
    "unavailable",
]
_BOT_CHECK_TERMS = [
    "robot or human",
    "verify you are human",
    "verify you're human",
    "are you a robot",
    "captcha",
]

logger = logging.getLogger(__name__)
stealth = Stealth()


class StockStatus(str, Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class StockResult:
    status: StockStatus
    details: str
    source: str = "browser"


class Checker:
    # buffer wait is not working when checking the page contents.  need to find different solution
    def __init__(
        self,
        user_agent=None,
        timeout=10,
        load_wait=0,
        buffer_wait=0,
        attempt_timeout_seconds=45,
    ):
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/115.0 Safari/537.36"
        )
        self.timeout = timeout
        self.load_wait = load_wait
        self.buffer_wait = buffer_wait
        self.attempt_timeout_seconds = attempt_timeout_seconds

    def _get_target_cart_button_with_timeout(self, url, attempt_timeout_seconds):
        """Run a single Playwright check in a daemon thread with a hard timeout."""
        result_queue = Queue(maxsize=1)

        def _worker():
            try:
                result_queue.put(("ok", self.get_target_cart_button(url)))
            except Exception as exc:
                result_queue.put(("err", exc))

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()

        try:
            status, payload = result_queue.get(timeout=attempt_timeout_seconds)
        except Empty:
            raise TimeoutError(
                f"get_target_cart_button exceeded {attempt_timeout_seconds}s for {url}"
            )

        if status == "err":
            raise payload

        return payload

    def _button_is_visible(self, button):
        logger.info("Checking button visibility")
        if button.get("hidden"):
            logger.info("Button is hidden due to 'hidden' attribute")
            return False
        logger.info("Button does not have 'hidden' attribute, assuming it is visible")
        return True

    def _find_out_of_stock_term(self, *parts):
        combined = " ".join(str(part or "").strip().lower() for part in parts)
        for term in _OUT_OF_STOCK_TERMS:
            if term in combined:
                return term
        return None

    def _button_indicates_out_of_stock(self, button):
        if not button:
            return False
        matched_term = self._find_out_of_stock_term(
            button.get("text"),
            button.get("aria_label") or button.get("aria-label"),
            button.get("data_test") or button.get("data-test"),
            button.get("page_stock_term"),
        )
        return matched_term is not None

    def _handle_indicates_out_of_stock(self, handle):
        if not handle:
            return False
        try:
            matched_term = self._find_out_of_stock_term(
                handle.inner_text(),
                handle.get_attribute("aria-label") or handle.get_attribute("aria_label"),
                handle.get_attribute("data-test") or handle.get_attribute("data_test"),
            )
            return matched_term is not None
        except Exception:
            return False

    def _get_page_out_of_stock_term(self, page):
        try:
            page_text = page.evaluate(
                "() => document.body ? document.body.innerText : ''"
            )
        except Exception:
            return None

        matched_term = self._find_out_of_stock_term(page_text)
        if matched_term:
            logger.info("Page text indicates out of stock: %s", matched_term)
        return matched_term

    def _get_bot_check_signal(self, page):
        try:
            title = page.title()
            body_text = page.evaluate(
                "() => document.body ? document.body.innerText : ''"
            )
        except Exception:
            return None

        combined_text = f"{title} {body_text}".lower()
        return next(
            (
                term
                for term in _BOT_CHECK_TERMS
                if term in combined_text
            ),
            None,
        )

    def _handle_is_visible(self, handle):
        if not handle:
            return False
        try:
            return handle.is_visible()
        except Exception:
            return False

    def _handle_is_enabled(self, handle):
        if not handle:
            return False
        try:
            return handle.is_enabled()
        except Exception:
            return False

    def _select_cart_button_handle(self, page, selectors=None):
        selectors = selectors or _CART_BUTTON_SELECTORS
        active_selector = None
        element_handle = None
        fallback_selector = None
        fallback_handle = None
        fallback_visible = False

        for sel in selectors:
            for handle in page.query_selector_all(sel):
                is_visible = self._handle_is_visible(handle)
                is_enabled = self._handle_is_enabled(handle)
                is_out_of_stock = self._handle_indicates_out_of_stock(handle)

                if is_visible and is_enabled and not is_out_of_stock:
                    logger.info("Resolved active buy add-to-cart selector: %s", sel)
                    return sel, handle

                if is_visible and (fallback_handle is None or not fallback_visible):
                    fallback_selector = sel
                    fallback_handle = handle
                    fallback_visible = True
                    logger.info(
                        "Found visible cart candidate with fallback state: selector=%s enabled=%s out_of_stock=%s",
                        sel,
                        is_enabled,
                        is_out_of_stock,
                    )

                if fallback_handle is None:
                    fallback_selector = sel
                    fallback_handle = handle

        if fallback_handle:
            logger.info(
                "No active buy button found; using fallback cart button selector: %s",
                fallback_selector,
            )

        return fallback_selector, fallback_handle

    def _selectors_for_url(self, url):
        hostname = (urlparse(url).hostname or "").lower()
        if hostname == "walmart.com" or hostname.endswith(".walmart.com"):
            return _WALMART_CART_BUTTON_SELECTORS
        return _CART_BUTTON_SELECTORS

    def fetch(self, url):
        headers = {"User-Agent": self.user_agent}
        resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def get_target_cart_button(self, url):
        with sync_playwright() as p:
            # Use Playwright's bundled Chromium with playwright-stealth for bot-detection bypass.
            # headless=True on bundled Chromium works reliably on Windows — no visible window.
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ]
            )
            btn_info = None
            click_ok = False
            try:
                cart_selectors = self._selectors_for_url(url)
                cart_selector_combined = ", ".join(cart_selectors)
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
                stealth.apply_stealth_sync(page)
                print(f"Navigating to: {url}")
                # Explicit 30-second navigation timeout so a stalled connection cannot
                # block the thread indefinitely.
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

                bot_check_signal = self._get_bot_check_signal(page)
                if bot_check_signal:
                    logger.warning(
                        "Bot-check page detected (%s); treating result as blocked: %s",
                        bot_check_signal,
                        url,
                    )
                    return None, None

                # Product pages expose fulfillment controls through provider-specific attributes.
                # We wait until any known candidate selector renders.
                # Target also applies dynamic content loading, so we wait for the button to appear and is clickable
                try:
                    page.wait_for_selector(cart_selector_combined, timeout=10000)
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
                                page.wait_for_load_state("networkidle", timeout=5000)
                                logger.info("Network idle reached after bot-check — stock state is final")
                            except Exception:
                                logger.info("Network idle timeout after bot-check; proceeding")
                            # Re-wait for the shipping button in its final post-render state
                            try:
                                page.wait_for_selector(cart_selector_combined, timeout=8000)
                                logger.info("Shipping button confirmed present after bot-check re-render")
                            except Exception:
                                logger.info("Shipping button not found after bot-check re-render; using current state")
                        except Exception as overlay_e:
                            logger.warning("Bot-check overlay did not clear (bot likely blocked request): %s", overlay_e)
                            return None, None
                except Exception as bot_e:
                    logger.info("Bot-check overlay evaluation error: %s", bot_e)

                page_stock_term = self._get_page_out_of_stock_term(page)

                # Resolve whichever known selector is present on the page.
                active_selector, element_handle = self._select_cart_button_handle(
                    page, cart_selectors
                )

                if not element_handle:
                    # Dump all button data-test attributes to help diagnose selector changes
                    try:
                        all_dt = page.evaluate(
                            "() => Array.from(document.querySelectorAll('button[data-test]'))"
                            ".map(b => b.getAttribute('data-test'))"
                        )
                        logger.warning(
                            "No known add-to-cart selector matched. "
                            "Button data-test values on page: %s",
                            all_dt,
                        )
                    except Exception as diag_e:
                        logger.warning("Could not read button data-test values: %s", diag_e)
                    logger.info("Playwright could not find button element for clicking")
                else:
                    click_target = active_selector
                    try:
                        if self._handle_indicates_out_of_stock(element_handle):
                            logger.info("Button text indicates out-of-stock or alternative; skipping click test")
                            click_ok = False
                        elif not self._handle_is_visible(element_handle):
                            logger.info("Button is not visible; skipping click test")
                            click_ok = False
                        elif not self._handle_is_enabled(element_handle):
                            logger.info("Button is not enabled; skipping click test")
                            click_ok = False
                        else:
                            page.click(click_target, timeout=3000)
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
                        else:
                            logger.info("Click failed for a reason other than overlay interception; not using overlay fallback")

                logger.info("Button Click Check Result: %s", "Enabled" if click_ok else "Disabled or Not Found")

                # Extract button attributes directly from the Playwright handle —
                # avoids serialising the full page HTML and parsing it with BeautifulSoup.
                if element_handle:
                    try:
                        # Re-evaluate the active cart control after any page re-render.
                        fresh_selector, fresh_handle = self._select_cart_button_handle(
                            page, cart_selectors
                        )
                        if fresh_handle:
                            active_selector = fresh_selector
                            element_handle = fresh_handle
                        btn_info = {
                            "hidden": element_handle.get_attribute("hidden") is not None,
                            "text": (element_handle.inner_text() or "").strip().lower(),
                            "aria_label": (element_handle.get_attribute("aria-label") or "").strip(),
                            "class": (element_handle.get_attribute("class") or ""),
                            "id": (element_handle.get_attribute("id") or ""),
                            "data_test": (element_handle.get_attribute("data-test") or ""),
                            "page_stock_term": page_stock_term or "",
                        }
                        logger.info("Button attributes extracted: data-test=%r", btn_info["data_test"])
                    except Exception as attr_e:
                        logger.warning("Could not read button attributes from handle: %s", attr_e)
            finally:
                browser.close()
        return btn_info, click_ok

    def check(self, url, max_retries=3, retry_delay=3, attempt_timeout_seconds=None):
        """Return a four-state result while preserving the legacy is_in_stock API."""
        in_stock, details = self.is_in_stock(
            url,
            max_retries=max_retries,
            retry_delay=retry_delay,
            attempt_timeout_seconds=attempt_timeout_seconds,
        )
        if in_stock:
            status = StockStatus.IN_STOCK
        elif "bot-check" in details.lower() or "blocked" in details.lower():
            status = StockStatus.BLOCKED
        elif "out of stock" in details.lower() or "alternative" in details.lower():
            status = StockStatus.OUT_OF_STOCK
        else:
            status = StockStatus.UNKNOWN
        return StockResult(status=status, details=details)

    def is_in_stock(self, url, max_retries=3, retry_delay=3, attempt_timeout_seconds=None):
        # Retry the full browser session on transient Playwright errors (e.g. "Target
        # crashed", "Target page closed").  Each retry recreates the browser from scratch.
        if attempt_timeout_seconds is None:
            attempt_timeout_seconds = self.attempt_timeout_seconds

        add_button, click_ok = None, False
        for attempt in range(1, max_retries + 1):
            try:
                add_button, click_ok = self._get_target_cart_button_with_timeout(
                    url, attempt_timeout_seconds
                )
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
            btn_text = add_button["text"]
            aria_label = add_button["aria_label"]
            logger.info(
                "Found add-to-cart button: class=%s, id=%r, data-test=%r, disabled=%s, hidden=%s",
                add_button["class"],
                add_button["id"],
                add_button["data_test"],
                click_ok,
                is_visible
            )
            if self._button_indicates_out_of_stock(add_button):
                logger.info("Add-to-cart button indicates out of stock or alternative: %r / %r", btn_text, aria_label)
                stock_signal = btn_text or aria_label or add_button.get("page_stock_term") or "out of stock"
                return False, f"Found button, but it indicates item is out of stock or alternative: {stock_signal}"
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
