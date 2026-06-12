# Pokemon Stock Notifier (Target example)

Simple Python app that polls a product page and notifies when it appears in stock.

Usage

1. Edit `config.yml` and add one or more items to the `products` list, including a `name` and `url` for each product.
2. (Optional) Set `webhook_url` to receive JSON payloads when an item becomes available.
3. (Optional) configure the `email` section to send email notifications.
4. The notifier validates your config at startup and will raise an error if required fields are missing or invalid.
5. Install dependencies:

```bash
python -m pip install -r "requirements.txt"
```

6. Run the notifier:

```bash
python notifier.py
```

If you are still using the old style config keys like `walmart_pokemon151_bb_url`, the notifier will continue to work by auto-detecting those URL keys.

Email configuration example:

```yaml
email:
  smtp_server: "smtp.example.com"
  smtp_port: 587
  username: "user@example.com"
  password: "supersecret"
  from: "notifier@example.com"
  to: "you@example.com, other@example.com"
  subject_prefix: "[Stock Alert]"
  use_tls: true
  use_ssl: false
```

The notifier sends email notifications for each product when stock is first detected.Notes

- The checker uses simple heuristics and may need adjustment for specific product pages. Edit `checker.py` to refine selectors or keywords.
- If desktop notifications don't work, the script prints a console fallback message.
