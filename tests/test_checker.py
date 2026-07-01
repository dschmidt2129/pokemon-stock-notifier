from unittest.mock import MagicMock, patch
import pytest

from checker import Checker

URL = "https://www.target.com/p/some-product/-/A-12345"


def _shipping_button_dict(text="add to cart", aria_label="", hidden=False, data_test="shippingButton"):
    """Return a button-info dict as produced by get_target_cart_button."""
    return {
        "hidden": hidden,
        "text": text.strip().lower(),
        "aria_label": aria_label,
        "class": "",
        "id": "",
        "data_test": data_test,
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
