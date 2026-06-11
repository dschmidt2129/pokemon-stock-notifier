# Pokemon Stock Notifier (Target example)

Simple Python app that polls a product page and notifies when it appears in stock.

Usage

1. Edit `config.yml` and add one or more items to the `products` list, including a `name` and `url` for each product.
2. (Optional) Set `webhook_url` to receive JSON payloads when an item becomes available.
3. Install dependencies:

```bash
python -m pip install -r "requirements.txt"
```

4. Run the notifier:

```bash
python notifier.py
```

If you are still using the old style config keys like `walmart_pokemon151_bb_url`, the notifier will continue to work by auto-detecting those URL keys.
Notes

- The checker uses simple heuristics and may need adjustment for specific product pages. Edit `checker.py` to refine selectors or keywords.
- If desktop notifications don't work, the script prints a console fallback message.
