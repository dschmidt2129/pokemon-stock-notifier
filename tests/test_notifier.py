import os

import pytest

from config import build_product_list, load_config, validate_config


def test_build_product_list_from_products():
    cfg = {"products": [{"name": "Example", "url": "https://example.com"}]}
    assert build_product_list(cfg) == [{"name": "Example", "url": "https://example.com"}]


def test_build_product_list_fallback_url_keys():
    cfg = {"first_url": "https://a.example.com", "second_url": "https://b.example.com"}
    assert build_product_list(cfg) == [
        {"name": "first_url", "url": "https://a.example.com"},
        {"name": "second_url", "url": "https://b.example.com"},
    ]


def test_build_product_list_skips_missing_url():
    cfg = {"products": [{"name": "Missing URL"}, {"name": "Valid", "url": "https://example.com"}]}
    assert build_product_list(cfg) == [{"name": "Valid", "url": "https://example.com"}]


def test_validate_config_rejects_missing_products():
    with pytest.raises(ValueError, match="No products configured"):
        validate_config({}, [])


def test_validate_config_rejects_missing_product_url():
    with pytest.raises(ValueError, match="Product entry missing 'url'"):
        validate_config({}, [{"name": "Broken"}])


def test_validate_config_rejects_nonpositive_interval():
    cfg = {"interval_seconds": 0}
    products = [{"name": "Example", "url": "https://example.com"}]
    with pytest.raises(ValueError, match="interval_seconds must be a positive integer"):
        validate_config(cfg, products)


def test_validate_config_rejects_negative_cooldown():
    cfg = {"stock_notification_cooldown_minutes": -1}
    products = [{"name": "Example", "url": "https://example.com"}]
    with pytest.raises(ValueError, match="stock_notification_cooldown_minutes must be a non-negative integer"):
        validate_config(cfg, products)


def test_validate_config_rejects_email_mapping_type():
    cfg = {"email": "not-a-map"}
    products = [{"name": "Example", "url": "https://example.com"}]
    with pytest.raises(ValueError, match="The 'email' config section must be a mapping"):
        validate_config(cfg, products)


def test_validate_config_rejects_partial_email_settings():
    cfg = {"email": {"smtp_server": "smtp.example.com", "from": "from@example.com", "to": ""}}
    products = [{"name": "Example", "url": "https://example.com"}]
    with pytest.raises(ValueError, match="Email config is incomplete"):
        validate_config(cfg, products)


def test_load_config(tmp_path):
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        "products:\n  - name: Example\n    url: https://example.com\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg["products"][0]["url"] == "https://example.com"


def test_load_config_merges_env_settings(tmp_path):
    config_file = tmp_path / "config.yml"
    env_file = tmp_path / ".env"

    config_file.write_text(
        "products:\n  - name: Example\n    url: https://example.com\n",
        encoding="utf-8",
    )
    env_file.write_text(
        "SMTP_SERVER=smtp.example.com\nEMAIL_USERNAME=user@example.com\nEMAIL_PASSWORD=pass\nEMAIL_FROM=sender@example.com\nEMAIL_TO=recipient@example.com\nEMAIL_USE_TLS=true\n",
        encoding="utf-8",
    )

    cfg = load_config(str(config_file), str(env_file))
    assert cfg["email"]["smtp_server"] == "smtp.example.com"
    assert cfg["email"]["username"] == "user@example.com"
    assert cfg["email"]["use_tls"] is True
