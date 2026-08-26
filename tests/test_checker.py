import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

from checker import Checker, StockStatus


URL = "https://www.target.com/p/some-product/-/A-12345"


def _button(text="add to cart", aria_label="", hidden=False, page_stock_term=""):
    return {
        "hidden": hidden,
        "text": text.strip().lower(),
        "aria_label": aria_label.strip(),
        "class": "",
        "id": "",
        "data_test": "shippingButton",
        "page_stock_term": page_stock_term,
    }


def _handle(text, *, visible=True, enabled=True, aria_label=""):
    handle = MagicMock()
    handle.inner_text = AsyncMock(return_value=text)
    attributes = {"aria-label": aria_label, "data-test": "shippingButton"}
    handle.get_attribute = AsyncMock(side_effect=lambda name: attributes.get(name, ""))
    handle.is_visible = AsyncMock(return_value=visible)
    handle.is_enabled = AsyncMock(return_value=enabled)
    return handle


class TestCheckerInit:
    def test_defaults(self):
        checker = Checker()
        assert "Mozilla" in checker.user_agent
        assert checker.timeout == 10
        assert checker.attempt_timeout_seconds == 45
        assert checker.browser_concurrency == 2

    def test_custom_values(self):
        checker = Checker(user_agent="TestAgent/2", timeout=30, attempt_timeout_seconds=12)
        assert checker.user_agent == "TestAgent/2"
        assert checker.timeout == 30
        assert checker.attempt_timeout_seconds == 12


class TestButtonSignals:
    def test_visibility(self):
        checker = Checker()
        assert checker._button_is_visible(_button()) is True
        assert checker._button_is_visible(_button(hidden=True)) is False

    @pytest.mark.parametrize("text", ["Find Alternative", "Sold out", "Check stores"])
    def test_out_of_stock_button_text(self, text):
        assert Checker()._button_indicates_out_of_stock(_button(text=text)) is True

    def test_out_of_stock_button_metadata(self):
        checker = Checker()
        assert checker._button_indicates_out_of_stock(_button(aria_label="Sold out online")) is True
        assert checker._button_indicates_out_of_stock(_button(page_stock_term="out of stock")) is True
        assert checker._button_indicates_out_of_stock(_button(text="Ship it")) is False

    async def test_handle_indicates_out_of_stock(self):
        checker = Checker()
        assert await checker._handle_indicates_out_of_stock(_handle("Find Alternative")) is True
        assert await checker._handle_indicates_out_of_stock(_handle("Add to cart")) is False


class TestSelectCartButtonHandle:
    async def test_prefers_visible_enabled_buy_button(self):
        alternative, buy = _handle("Find Alternative"), _handle("Add to cart")
        page = MagicMock()
        page.query_selector_all = AsyncMock(
            side_effect=lambda selector: [alternative, buy]
            if selector == 'button[data-test="shippingButton"]'
            else []
        )

        selector, handle = await Checker()._select_cart_button_handle(page)

        assert selector == 'button[data-test="shippingButton"]'
        assert handle is buy

    async def test_uses_visible_fallback_when_no_buy_button_exists(self):
        alternative = _handle("Find Alternative")
        page = MagicMock()
        page.query_selector_all = AsyncMock(
            side_effect=lambda selector: [alternative]
            if selector == 'button[data-test="shippingButton"]'
            else []
        )

        selector, handle = await Checker()._select_cart_button_handle(page)

        assert selector == 'button[data-test="shippingButton"]'
        assert handle is alternative


class TestWalmartSupport:
    def test_walmart_urls_use_walmart_selectors(self):
        selectors = Checker()._selectors_for_url("https://www.walmart.com/ip/example/123")
        assert 'button[data-automation-id="add-to-cart"]' in selectors

    def test_non_walmart_urls_keep_target_selectors(self):
        selectors = Checker()._selectors_for_url("https://www.target.com/p/example/-/A-123")
        assert selectors[0] == 'button[data-test="shippingButton"]'

    async def test_selects_walmart_add_to_cart_selector(self):
        buy = _handle("Add to cart")
        selector = 'button[data-automation-id="add-to-cart"]'
        page = MagicMock()
        page.query_selector_all = AsyncMock(
            side_effect=lambda current_selector: [buy]
            if current_selector == selector
            else []
        )

        selected_selector, handle = await Checker()._select_cart_button_handle(
            page, [selector]
        )

        assert selected_selector == selector
        assert handle is buy

    async def test_robot_or_human_page_is_detected_as_bot_check(self):
        page = MagicMock()
        page.title = AsyncMock(return_value="Robot or human?")
        page.evaluate = AsyncMock(return_value="Please verify you are human")

        assert await Checker()._get_bot_check_signal(page) == "robot or human"


class TestFetch:
    def test_returns_text_on_success(self):
        with patch("checker.requests.get") as mock_get:
            mock_get.return_value.text = "<html>ok</html>"
            result = Checker().fetch(URL)
        assert result == "<html>ok</html>"

    def test_raises_on_http_error(self):
        with patch("checker.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.side_effect = requests.HTTPError("404")
            with pytest.raises(requests.HTTPError):
                Checker().fetch(URL)

    def test_custom_user_agent_sent(self):
        with patch("checker.requests.get") as mock_get:
            mock_get.return_value.text = ""
            Checker(user_agent="TestAgent/2").fetch(URL)
        assert mock_get.call_args.kwargs["headers"]["User-Agent"] == "TestAgent/2"


class TestIsInStock:
    def _checker(self, result):
        checker = Checker()
        checker._get_target_cart_button_with_timeout = AsyncMock(return_value=result)
        return checker

    async def test_in_stock_when_click_succeeds(self):
        in_stock, details = await self._checker((_button(), True)).is_in_stock(URL)
        assert in_stock is True
        assert "click succeeded" in details

    @pytest.mark.parametrize(
        "result, expected",
        [
            ((_button(), False), "disabled"),
            ((_button(hidden=True), True), "not visible"),
            ((_button(text="Find Alternative"), True), "out of stock or alternative"),
            ((None, False), "No clear stock indicators"),
        ],
    )
    async def test_non_buy_states(self, result, expected):
        checker = self._checker(result)
        checker.fetch = MagicMock(return_value="page content")
        in_stock, details = await checker.is_in_stock(URL)
        assert in_stock is False
        assert expected in details

    async def test_retries_bot_checks_and_can_succeed(self):
        checker = Checker()
        checker._get_target_cart_button_with_timeout = AsyncMock(
            side_effect=[(None, None), (None, None), (_button(), True)]
        )
        with patch("checker.asyncio.sleep", new_callable=AsyncMock) as sleep:
            in_stock, _ = await checker.is_in_stock(URL, retry_delay=7)
        assert in_stock is True
        assert checker._get_target_cart_button_with_timeout.await_count == 3
        assert sleep.await_count == 2
        sleep.assert_awaited_with(7)

    async def test_returns_error_after_retry_exhaustion(self):
        checker = Checker()
        checker._get_target_cart_button_with_timeout = AsyncMock(
            side_effect=TimeoutError("timed out")
        )
        with patch("checker.asyncio.sleep", new_callable=AsyncMock):
            in_stock, details = await checker.is_in_stock(URL, max_retries=2, retry_delay=0)
        assert in_stock is False
        assert "2 attempts" in details
        assert "timed out" in details

    async def test_uses_instance_timeout_default(self):
        checker = Checker(attempt_timeout_seconds=17)
        checker._get_target_cart_button_with_timeout = AsyncMock(return_value=(_button(), True))
        await checker.is_in_stock(URL, max_retries=1)
        assert checker._get_target_cart_button_with_timeout.await_args.args[1] == 17


class TestCheck:
    async def test_maps_in_stock_to_result(self):
        checker = Checker()
        checker.is_in_stock = AsyncMock(return_value=(True, "available"))
        result = await checker.check(URL)
        assert result.status is StockStatus.IN_STOCK

    async def test_maps_bot_check_to_blocked(self):
        checker = Checker()
        checker.is_in_stock = AsyncMock(return_value=(False, "Bot-check overlay blocked all attempts"))
        result = await checker.check(URL)
        assert result.status is StockStatus.BLOCKED


class TestBrowserRecovery:
    async def test_timeout_resets_shared_browser(self):
        checker = Checker()
        checker.get_target_cart_button = AsyncMock(side_effect=asyncio.TimeoutError)
        checker._reset_browser = AsyncMock()

        with pytest.raises(TimeoutError):
            await checker._get_target_cart_button_with_timeout(URL, 1)

        checker._reset_browser.assert_awaited_once()

    async def test_aclose_resets_shared_browser(self):
        checker = Checker()
        checker._reset_browser = AsyncMock()
        await checker.aclose()
        checker._reset_browser.assert_awaited_once()