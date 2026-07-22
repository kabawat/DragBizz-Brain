---
module: inventory
feature: low-stock
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Low Stock Alerts

## Overview

DragBizz flags products running low in two ways: **push notifications** to the store owner the moment a product drops to its low-stock threshold, and a **daily email digest** summarizing all low-stock items. A product is "low" when its available quantity is above zero but at or below its threshold (default **10** units).

## Workflow

1. **Badges** — the Stocks list marks items as Low Stock (orange) or Out of Stock (red) automatically.
2. **Push notification** — when a product *transitions* into low stock (e.g., a sale takes it from 12 to 9 with threshold 10), the store owner's devices get: "Low stock alert — {product} has only {qty} left (threshold {n})". Repeat alerts for the same product are cooled down for 24 hours.
3. **Daily digest** — every day (early morning), stores with alerts enabled and a valid store email receive a low-stock digest email listing all items at or below threshold.
4. **Analytics** — the Stock analytics page shows a "Low Stock Items" metric.

## Business rules

- Threshold default is 10 units per product; the store-wide default comes from the store's inventory alert settings.
- Store-level controls: alerts on/off, push (FCM) on/off, email digest on/off, and the default threshold — managed via store settings.
- There is currently **no per-product threshold field in the app UI**; thresholds follow the store default.
- Push alerts go to the **store owner's** registered devices (ensure push notifications are enabled in Settings → Notifications).
- Alerts fire on the transition into low stock, not continuously; the 24-hour cooldown prevents repeat pings.
- Out of Stock (zero available) is shown as its own status, distinct from Low Stock.

## Examples

- "Tell me which items are running low" → Stocks list Low Stock badges, or the stock analytics low-stock metric (the voice assistant's stock summary also includes totals).
- "Why didn't I get a second alert for the same product today?" → the 24-hour cooldown per product.

## Errors

- No digest email received — check that store email is set, alerts and email digest are enabled, and the store is active.
- No push received — enable push in Settings → Notifications and ensure the owner device is registered; push alerts also respect the store's FCM setting.

## FAQ

**Q: Can I set a different threshold for each product?** 
Not from the app UI today — the store default threshold (10 by default) applies. Changing the store default affects newly created inventory.

**Q: Who receives low-stock notifications?** 
Push goes to the store owner's devices; the daily digest goes to the store's email address.

**Q: When does the daily digest arrive?** 
Once a day in the early morning (server schedule), covering all items at or below threshold at that time.
