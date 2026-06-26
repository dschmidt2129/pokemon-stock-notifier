import os
import sys
from unittest.mock import MagicMock

# Ensure project root is on sys.path so tests can import top-level modules
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Stub out playwright so tests can import checker.py without the package installed.
# All Playwright interactions in tests are mocked at the get_target_cart_button level,
# so the real playwright library is never needed during the test run.
if "playwright" not in sys.modules:
    _pw = MagicMock()
    sys.modules["playwright"] = _pw
    sys.modules["playwright.sync_api"] = _pw
