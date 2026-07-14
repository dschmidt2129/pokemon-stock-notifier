import os
from pathlib import Path

import yaml


EMAIL_ENV_KEYS = (
    "SMTP_SERVER",
    "SMTP_PORT",
    "EMAIL_USERNAME",
    "EMAIL_PASSWORD",
    "EMAIL_FROM",
    "EMAIL_TO",
    "EMAIL_SUBJECT_PREFIX",
    "EMAIL_BODY",
    "EMAIL_USE_TLS",
    "EMAIL_USE_SSL",
)


def parse_env_bool(value):
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    return None


def load_dotenv(path=".env"):  # pragma: no cover
    env_path = Path(path)
    if not env_path.is_file():
        return {}

    env = {}
    with env_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            env[key] = value
    return env


def load_email_env_config(path=".env"):
    env = load_dotenv(path)
    for key in EMAIL_ENV_KEYS:
        if key in os.environ:
            env[key] = os.environ[key]

    if not env:
        return {}

    email_cfg = {
        "smtp_server": env.get("SMTP_SERVER"),
        "smtp_port": env.get("SMTP_PORT"),
        "username": env.get("EMAIL_USERNAME"),
        "password": env.get("EMAIL_PASSWORD"),
        "from": env.get("EMAIL_FROM"),
        "to": env.get("EMAIL_TO"),
        "subject_prefix": env.get("EMAIL_SUBJECT_PREFIX"),
        "body": env.get("EMAIL_BODY"),
        "use_tls": parse_env_bool(env.get("EMAIL_USE_TLS")),
        "use_ssl": parse_env_bool(env.get("EMAIL_USE_SSL")),
    }

    if any(email_cfg.get(key) for key in ("smtp_server", "username", "password", "from", "to")):
        return {"email": {k: v for k, v in email_cfg.items() if v is not None}}
    return {}


def load_config(path="config.yml", env_path=".env"):
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    email_env = load_email_env_config(env_path)
    if email_env:
        cfg["email"] = {**cfg.get("email", {}), **email_env["email"]}

    return cfg


def build_product_list(cfg):
    products = cfg.get("products")
    if products:
        return [
            {
                "name": product.get("name") or product.get("url"),
                "url": product["url"],
            }
            for product in products
            if product.get("url")
        ]

    fallback = []
    for key, value in cfg.items():
        if key.endswith("_url") and isinstance(value, str):
            fallback.append({"name": key, "url": value})

    return fallback


def validate_config(cfg, products):
    if not products:
        raise ValueError("No products configured in config.yml")

    for product in products:
        if not product.get("url"):
            raise ValueError(f"Product entry missing 'url': {product}")

    if cfg.get("interval_seconds") is not None:
        interval = cfg["interval_seconds"]
        if not isinstance(interval, int) or interval <= 0:
            raise ValueError("interval_seconds must be a positive integer")

    if cfg.get("stock_notification_cooldown_minutes") is not None:
        cooldown = cfg["stock_notification_cooldown_minutes"]
        if not isinstance(cooldown, int) or cooldown < 0:
            raise ValueError(
                "stock_notification_cooldown_minutes must be a non-negative integer"
            )

    if cfg.get("check_delay_seconds") is not None:
        delay = cfg["check_delay_seconds"]
        if not isinstance(delay, int) or delay < 0:
            raise ValueError("check_delay_seconds must be a non-negative integer")

    if cfg.get("checker_attempt_timeout_seconds") is not None:
        attempt_timeout = cfg["checker_attempt_timeout_seconds"]
        if not isinstance(attempt_timeout, int) or attempt_timeout <= 0:
            raise ValueError("checker_attempt_timeout_seconds must be a positive integer")

    email_cfg = cfg.get("email")
    if email_cfg is None:
        return

    if not isinstance(email_cfg, dict):
        raise ValueError("The 'email' config section must be a mapping")

    enabled_keys = ("smtp_server", "username", "password", "from", "to")
    enabled = any(bool(email_cfg.get(k)) for k in enabled_keys)
    if not enabled:
        return

    missing = [field for field in ("smtp_server", "from", "to") if not email_cfg.get(field)]
    if missing:
        raise ValueError(
            "Email config is incomplete. Add the following fields: " + ", ".join(missing)
        )
