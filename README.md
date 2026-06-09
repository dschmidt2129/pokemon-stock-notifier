# Pokemon Stock Notifier (Target example)

Simple Python app that polls a product page and notifies when it appears in stock.

Usage

1. Edit `config.yml` and set `product_url` to the Target product page you want to monitor.
2. (Optional) Set `webhook_url` to receive JSON payloads when an item becomes available.
3. Install dependencies:

```bash
python -m pip install -r "requirements.txt"
```

4. Run the notifier:

```bash
python notifier.py
```

Notes

- The checker uses simple heuristics and may need adjustment for specific product pages. Edit `target_checker.py` to refine selectors or keywords.
- If desktop notifications don't work, the script prints a console fallback message.
