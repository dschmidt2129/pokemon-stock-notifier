from unittest.mock import MagicMock, patch
import pytest

from checker import Checker

URL = "https://www.target.com/p/some-product/-/A-12345"


def _shipping_button_dict(
    text="add to cart",
    aria_label="",
    hidden=False,
    data_test="shippingButton",
    page_stock_term="",
):
    """Return a button-info dict as produced by get_target_cart_button."""
    return {
        "hidden": hidden,
        "text": text.strip().lower(),
        "aria_label": aria_label.strip(),
        "class": "",
        "id": "",
        "data_test": data_test,
        "page_stock_term": page_stock_term,
    }


# ---------------------------------------------------------------------------
# Checker.__init__
# ---------------------------------------------------------------------------

class TestCheckerInit:
    def test_default_user_agent_set(self):
        c = Checker()
        assert "Mozilla" in c.user_agent

    def test_custom_user_agent(self):
        c = Checker(user_agent="MyBot/1.0")
        assert c.user_agent == "MyBot/1.0"

    def test_default_timeout(self):
        assert Checker().timeout == 10

    def test_custom_timeout(self):
        assert Checker(timeout=30).timeout == 30

    def test_default_attempt_timeout(self):
        assert Checker().attempt_timeout_seconds == 45

    def test_custom_attempt_timeout(self):
        assert Checker(attempt_timeout_seconds=12).attempt_timeout_seconds == 12


# ---------------------------------------------------------------------------
# Checker._button_is_visible
# ---------------------------------------------------------------------------

class TestButtonIsVisible:
    def test_visible_button(self):
        btn = _shipping_button_dict(hidden=False)
        assert Checker()._button_is_visible(btn) is True

    def test_hidden_button(self):
        btn = _shipping_button_dict(hidden=True)
        assert Checker()._button_is_visible(btn) is False


# ---------------------------------------------------------------------------
# Checker._button_indicates_out_of_stock & _handle_indicates_out_of_stock
# ---------------------------------------------------------------------------

class TestButtonIndicatesOutOfStock:
    def test_find_alternative_in_text(self):
        btn = _shipping_button_dict(text="Find Alternative")
        assert Checker()._button_indicates_out_of_stock(btn) is True

    def test_find_alternatives_in_aria_label(self):
        btn = _shipping_button_dict(text="", aria_label="Find alternatives for Twilight Masquerade ETB")
        assert Checker()._button_indicates_out_of_stock(btn) is True

    def test_sold_out(self):
        btn = _shipping_button_dict(text="Sold out")
        assert Checker()._button_indicates_out_of_stock(btn) is True

    def test_check_stores(self):
        btn = _shipping_button_dict(text="Check stores")
        assert Checker()._button_indicates_out_of_stock(btn) is True

    def test_page_stock_term_marks_button_out_of_stock(self):
        btn = _shipping_button_dict(text="Add to cart", page_stock_term="out of stock")
        assert Checker()._button_indicates_out_of_stock(btn) is True

    def test_normal_buy_button_not_out_of_stock(self):
        btn = _shipping_button_dict(text="Ship it")
        assert Checker()._button_indicates_out_of_stock(btn) is False

    def test_none_or_empty(self):
        assert Checker()._button_indicates_out_of_stock(None) is False
        assert Checker()._button_indicates_out_of_stock({}) is False

    def test_handle_indicates_out_of_stock(self):
        handle = MagicMock()
        handle.inner_text.return_value = "Find Alternative"
        handle.get_attribute.return_value = ""
        assert Checker()._handle_indicates_out_of_stock(handle) is True

        handle.inner_text.return_value = "Add to cart"
        assert Checker()._handle_indicates_out_of_stock(handle) is False


class TestSelectCartButtonHandle:
    def _handle(
        self,
        text,
        *,
        visible=True,
        enabled=True,
        aria_label="",
        data_test="shippingButton",
    ):
        handle = MagicMock()
        handle.inner_text.return_value = text
        attrs = {
            "aria-label": aria_label,
            "aria_label": aria_label,
            "data-test": data_test,
            "data_test": data_test,
        }
        handle.get_attribute.side_effect = lambda name: attrs.get(name, "")
        handle.is_visible.return_value = visible
        handle.is_enabled.return_value = enabled
        return handle

    def test_prefers_visible_enabled_buy_button(self):
        alternative = self._handle("Find Alternative")
        buy = self._handle("Add to cart")
        page = MagicMock()
        page.query_selector_all.side_effect = lambda sel: [alternative, buy] if sel == 'button[data-test="shippingButton"]' else []

        selector, handle = Checker()._select_cart_button_handle(page)

        assert selector == 'button[data-test="shippingButton"]'
        assert handle is buy

    def test_ignores_hidden_buy_button_and_uses_visible_fallback(self):
        hidden_buy = self._handle("Add to cart", visible=False)
        alternative = self._handle("Find Alternative", visible=True)
        page = MagicMock()
        page.query_selector_all.side_effect = lambda sel: [hidden_buy, alternative] if sel == 'button[data-test="shippingButton"]' else []

        selector, handle = Checker()._select_cart_button_handle(page)

        assert selector == 'button[data-test="shippingButton"]'
        assert handle is alternative

    def test_returns_visible_alternative_when_no_buy_button_exists(self):
        alternative = self._handle("Find Alternative")
        page = MagicMock()
        page.query_selector_all.side_effect = lambda sel: [alternative] if sel == 'button[data-test="shippingButton"]' else []

        selector, handle = Checker()._select_cart_button_handle(page)

        assert selector == 'button[data-test="shippingButton"]'
        assert handle is alternative


# ---------------------------------------------------------------------------
# Checker.fetch
# ---------------------------------------------------------------------------

class TestFetch:
    def test_returns_text_on_success(self):
        with patch("checker.requests.get") as mock_get:
            mock_get.return_value.text = "<html>ok</html>"
            mock_get.return_value.raise_for_status = lambda: None
            result = Checker().fetch(URL)
        assert result == "<html>ok</html>"

    def test_raises_on_http_error(self):
        import requests as req
        with patch("checker.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.side_effect = req.HTTPError("404")
            with pytest.raises(req.HTTPError):
                Checker().fetch(URL)

    def test_custom_user_agent_sent(self):
        with patch("checker.requests.get") as mock_get:
            mock_get.return_value.text = ""
            mock_get.return_value.raise_for_status = lambda: None
            Checker(user_agent="TestAgent/2").fetch(URL)
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["User-Agent"] == "TestAgent/2"


# ---------------------------------------------------------------------------
# Checker.is_in_stock  (get_target_cart_button is mocked throughout)
# ---------------------------------------------------------------------------

class TestIsInStock:
    def _checker(self):
        return Checker()

    # --- in-stock path ---

    def test_in_stock_when_click_ok_and_button_present(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(return_value=(_shipping_button_dict(), True))
        in_stock, details = c.is_in_stock(URL)
        assert in_stock is True
        assert "click succeeded" in details

    def test_details_contains_button_text_when_in_stock(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(return_value=(_shipping_button_dict(text="Add to cart"), True))
        _, details = c.is_in_stock(URL)
        assert "add to cart" in details

    def test_details_falls_back_to_aria_label_when_text_empty(self):
        btn = _shipping_button_dict(text="", aria_label="Add to cart for Widget")
        c = self._checker()
        c.get_target_cart_button = MagicMock(return_value=(btn, True))
        _, details = c.is_in_stock(URL)
        assert "Add to cart for Widget" in details

    # --- disabled button path ---

    def test_out_of_stock_when_click_not_ok(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(return_value=(_shipping_button_dict(), False))
        in_stock, details = c.is_in_stock(URL)
        assert in_stock is False
        assert "disabled" in details

    # --- hidden button path ---

    def test_out_of_stock_when_button_hidden(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(return_value=(_shipping_button_dict(hidden=True), True))
        in_stock, details = c.is_in_stock(URL)
        assert in_stock is False
        assert "not visible" in details

    # --- out of stock / alternative button path ---

    def test_out_of_stock_when_button_is_find_alternative(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(return_value=(_shipping_button_dict(text="Find Alternative"), True))
        in_stock, details = c.is_in_stock(URL)
        assert in_stock is False
        assert "out of stock or alternative" in details

    def test_out_of_stock_when_button_aria_label_indicates_sold_out(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(return_value=(_shipping_button_dict(text="", aria_label="Sold out online"), True))
        in_stock, details = c.is_in_stock(URL)
        assert in_stock is False
        assert "out of stock or alternative" in details

    def test_out_of_stock_when_page_text_indicates_out_of_stock(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(
            return_value=(_shipping_button_dict(text="Add to cart", page_stock_term="out of stock"), True)
        )
        in_stock, details = c.is_in_stock(URL)
        assert in_stock is False
        assert "out of stock or alternative" in details
        assert "out of stock" in details

    # --- no button found path ---

    def test_out_of_stock_when_no_button_found(self):
        c = self._checker()
        # (None, False) = page loaded normally but no button present
        c.get_target_cart_button = MagicMock(return_value=(None, False))
        c.fetch = MagicMock(return_value="<html>nothing here</html>")
        in_stock, details = c.is_in_stock(URL)
        assert in_stock is False
        assert "No clear stock indicators" in details

    def test_snippet_included_in_details_when_no_button(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(return_value=(None, False))
        c.fetch = MagicMock(return_value="page content here")
        _, details = c.is_in_stock(URL)
        assert "page content here" in details

    def test_snippet_empty_when_fetch_raises(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(return_value=(None, False))
        c.fetch = MagicMock(side_effect=Exception("network error"))
        _, details = c.is_in_stock(URL)
        assert "No clear stock indicators" in details
        assert "Snippet: " in details

    # --- bot-check blocked path ---

    def test_returns_false_when_bot_check_blocks_all_attempts(self):
        c = self._checker()
        # (None, None) is the sentinel returned when the overlay never clears
        c.get_target_cart_button = MagicMock(return_value=(None, None))
        with patch("checker.time.sleep"):
            in_stock, details = c.is_in_stock(URL, max_retries=3, retry_delay=0)
        assert in_stock is False
        assert "Bot-check overlay blocked all attempts" in details

    def test_bot_check_retries_full_count(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(return_value=(None, None))
        with patch("checker.time.sleep"):
            c.is_in_stock(URL, max_retries=3, retry_delay=0)
        assert c.get_target_cart_button.call_count == 3

    def test_bot_check_sleep_called_between_retries(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(return_value=(None, None))
        with patch("checker.time.sleep") as mock_sleep:
            c.is_in_stock(URL, max_retries=3, retry_delay=7)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(7)

    def test_bot_check_succeeds_on_later_attempt(self):
        """If the first attempt is bot-blocked but a later one succeeds, report in-stock."""
        c = self._checker()
        call_count = 0
        def side_effect(url):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return (None, None)  # bot-blocked
            return (_shipping_button_dict(), True)
        c.get_target_cart_button = side_effect
        with patch("checker.time.sleep"):
            in_stock, _ = c.is_in_stock(URL, retry_delay=0)
        assert in_stock is True
        assert call_count == 3

    def test_bot_check_no_sleep_on_single_attempt(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(return_value=(None, None))
        with patch("checker.time.sleep") as mock_sleep:
            c.is_in_stock(URL, max_retries=1, retry_delay=5)
        mock_sleep.assert_not_called()

    # --- retry logic ---

    def test_retries_on_exception_then_succeeds(self):
        c = self._checker()
        call_count = 0
        def side_effect(url):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("Target crashed")
            return (_shipping_button_dict(), True)
        c.get_target_cart_button = side_effect
        with patch("checker.time.sleep"):
            in_stock, _ = c.is_in_stock(URL, retry_delay=0)
        assert in_stock is True
        assert call_count == 3

    def test_returns_false_after_all_retries_exhausted(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(side_effect=RuntimeError("Target crashed"))
        with patch("checker.time.sleep"):
            in_stock, details = c.is_in_stock(URL, max_retries=3, retry_delay=0)
        assert in_stock is False
        assert "3 attempts" in details

    def test_retry_count_respected(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(side_effect=RuntimeError("crash"))
        with patch("checker.time.sleep"):
            c.is_in_stock(URL, max_retries=2, retry_delay=0)
        assert c.get_target_cart_button.call_count == 2

    def test_sleep_called_between_retries(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(side_effect=RuntimeError("crash"))
        with patch("checker.time.sleep") as mock_sleep:
            c.is_in_stock(URL, max_retries=3, retry_delay=5)
        # sleep is called between attempts, not after the last one
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(5)

    def test_no_sleep_on_single_attempt_failure(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(side_effect=RuntimeError("crash"))
        with patch("checker.time.sleep") as mock_sleep:
            c.is_in_stock(URL, max_retries=1, retry_delay=5)
        mock_sleep.assert_not_called()

    def test_error_message_contains_exception_text(self):
        c = self._checker()
        c.get_target_cart_button = MagicMock(side_effect=RuntimeError("Target crashed"))
        with patch("checker.time.sleep"):
            _, details = c.is_in_stock(URL, max_retries=1)
        assert "Target crashed" in details

    def test_returns_false_after_timeout_retries_exhausted(self):
        c = self._checker()
        c._get_target_cart_button_with_timeout = MagicMock(
            side_effect=TimeoutError("timed out")
        )
        with patch("checker.time.sleep"):
            in_stock, details = c.is_in_stock(URL, max_retries=2, retry_delay=0)
        assert in_stock is False
        assert "2 attempts" in details
        assert "timed out" in details

    def test_uses_instance_attempt_timeout_default(self):
        c = Checker(attempt_timeout_seconds=17)

        captured = {}

        def side_effect(url, timeout_seconds):
            captured["timeout_seconds"] = timeout_seconds
            return _shipping_button_dict(), True

        c._get_target_cart_button_with_timeout = MagicMock(side_effect=side_effect)
        in_stock, _ = c.is_in_stock(URL, max_retries=1)
        assert in_stock is True
        assert captured["timeout_seconds"] == 17
