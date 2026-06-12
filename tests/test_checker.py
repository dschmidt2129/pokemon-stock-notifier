from checker import Checker


def test_is_in_stock_add_to_cart_text():
    checker = Checker()
    checker.fetch = lambda url: "<html><body>Add to cart now</body></html>"
    assert checker.is_in_stock("https://example.com")[0] is True


def test_is_in_stock_sold_out_text():
    checker = Checker()
    checker.fetch = lambda url: "<html><body>Sold out</body></html>"
    assert checker.is_in_stock("https://example.com")[0] is False


def test_is_in_stock_ship_it_text():
    checker = Checker()
    checker.fetch = lambda url: "<html><body>Ship it today</body></html>"
    assert checker.is_in_stock("https://example.com")[0] is True


def test_is_in_stock_button_text():
    checker = Checker()
    checker.fetch = lambda url: "<html><body><button>Add to Cart</button></body></html>"
    assert checker.is_in_stock("https://example.com")[0] is True


def test_is_in_stock_falls_back_to_snippet():
    checker = Checker()
    checker.fetch = lambda url: "<html><body>No stock information here</body></html>"
    in_stock, details = checker.is_in_stock("https://example.com")
    assert in_stock is False
    assert "No clear stock indicators" in details
