# Pokemon Stock Notifier (Target example)

Simple Python app that polls a product page and notifies when it appears in stock.

Usage

1. Edit `config.yml` and add one or more items to the `products` list, including a `name` and `url` for each product.
2. (Optional) Set `webhook_url` to receive JSON payloads when an item becomes available.
3. (Optional) configure a local `.env` file to send email notifications.
5. The notifier supports `stock_notification_cooldown_minutes` to avoid spamming repeated in-stock alerts for the same product.
6. The notifier validates your config at startup and will raise an error if required fields are missing or invalid.
7. Install dependencies:

```bash
python -m pip install -r "requirements.txt"
```

6. Run the notifier:

```bash
python notifier.py
```

If you are still using the old style config keys like `walmart_pokemon151_bb_url`, the notifier will continue to work by auto-detecting those URL keys.

Email configuration example:

Create a local `.env` file next to `notifier.py` and set your SMTP credentials there. This keeps email secrets out of `config.yml`.

```env
SMTP_SERVER=smtp.example.com
SMTP_PORT=587
EMAIL_USERNAME=user@example.com
EMAIL_PASSWORD=supersecret
EMAIL_FROM=notifier@example.com
EMAIL_TO=you@example.com,other@example.com
EMAIL_SUBJECT_PREFIX=[Stock Alert]
EMAIL_BODY=The {product_name} is back in stock! Check it out here: {url}
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false
```

Optional cooldown example:

```yaml
stock_notification_cooldown_minutes: 5
```

Optional checker timeout example:

```yaml
checker_attempt_timeout_seconds: 45
```

This per-product timeout ensures a stuck browser check fails fast and the notifier loop continues.

The notifier sends email notifications for each product when stock is first detected and will resend after the configured cooldown if the product remains in stock.

- The checker uses simple heuristics and may need adjustment for specific product pages. Edit `checker.py` to refine selectors or keywords.
- If desktop notifications don't work, the script prints a console fallback message.
