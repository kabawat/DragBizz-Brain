---
module: sales-order
feature: public-catalog
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Public Catalog (Catalog Link & QR)

## Overview

Every store gets a public online catalog at a shareable link (`/c/{catalogId}`) — customers open it from the store's **Catalog QR** or link without any login. They see your products with images, prices, and discounts, can search and filter by category, add items to a cart, and place an order online. An **in-store QR** variant (with a dining/counter location) is designed for table ordering.

## What visitors see

- Store header: logo, name, city/state, Share button, cart, and a "Connect Store" call button.
- Product cards: image, brand, category, selling price with struck-through MRP and "% OFF" when discounted, and an **Out of Stock / Sold Out** badge for unavailable items. Exact stock quantity is never shown.
- Search (by name/brand/SKU) and category filter.
- A WhatsApp enquire button per product, and Add To Cart with quantity stepper.
- Cart drawer ("Bag Details") with subtotal, free delivery, total, and **Secure Checkout**.

## Sharing the catalog (store side)

1. Settings → Store (or Sales Orders page) → **Catalog QR**.
2. Optionally add an **In-Store Dining Location** (e.g., "Table 4, Counter A") — this QR opens the catalog in in-store mode: no delivery address and no OTP at checkout.
3. Copy the link, download a printable PDF, or print the QR.

## Business rules

- Only **active** products with catalog visibility on appear; products can be hidden per item via the "show in catalog" setting.
- Prices shown are selling price and MRP; purchase/cost data is never exposed.
- The catalog ID is generated with the store and can be regenerated (old links/QRs then stop working).
- Public pages are rate-limited; very rapid refreshes get "Too many requests, please try again later."

## Examples

- "Customers ko online menu dikhana hai" → print the Catalog QR at the counter.
- "Table ordering chahiye" → one QR per table with its dining location.
- "Ek product catalog se hatana hai" → edit the product → turn off catalog visibility.

## Errors

- "Catalog not found" / "Catalog Missing" — wrong or regenerated catalog ID.
- "No products found" — filters/search matched nothing; Reset all filters.
- "Store contact information is missing" — the Connect Store button needs a store phone.

## FAQ

**Q: Do customers need an account?** 
No — the catalog and ordering are fully public; identity is confirmed via OTP at checkout.

**Q: Can customers see how many units are left?** 
No — only an Out of Stock badge when an item is unavailable.

**Q: Can I take online payments through the catalog?** 
Catalog orders are placed unpaid; payment is collected at delivery/counter or via a payment link afterwards.
