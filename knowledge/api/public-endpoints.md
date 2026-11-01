---
module: api
feature: public-endpoints
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Public Endpoints (No Login Required)

## Overview

A small set of DragBizz endpoints work **without any login** — they power the customer-facing pages: shared invoices, the public catalog and online ordering, purchase-order links for suppliers, order tracking, and payment collect-links. There is no partner API programme or API-key access today; these endpoints exist to serve the public share links the app generates.

## What's public

| Purpose | How it's used |
|---|---|
| **Public invoice** | An invoice share link opens the invoice by its public ID — customer sees store details, items, totals, and payment status. Rate limit 30/min. |
| **Public catalog** | The catalog link/QR (`/c/{catalogId}`) lists the store's categories and visible products (name, brand, price/MRP, images; never stock counts or cost). Rate limit 100/min. |
| **Public sales order** | Placing an order from the catalog (with 5-digit OTP verify) and tracking it by its public order ID. Rate limit 10/min. |
| **Public purchase order** | A PO share link lets a supplier view the order (view-only — no approve/reject from the link). |
| **Collect-link resolve** | A payment collect-link token resolves to the payable amount/details and opens the hosted payment page. Links expire (7 days for khata links). Rate limit 30/min. |
| **Bulk-upload templates** | Sample import templates (customers, products, opening balance) are served publicly for download. |

## Business rules

- Every public object uses a random **public ID or token** — links only work if you share them; there is no way to list or browse other data.
- Only presentation-safe fields are exposed: no cost prices, stock quantities, khata balances, or internal IDs.
- All public endpoints are rate-limited; heavy automated polling gets "Too many requests, please try again later."
- Regenerating a store's catalog ID, or a payment link expiring/being replaced, invalidates the old link.
- Internal service-to-service APIs (auth, subscription sync, webhooks) are **not** for external use and are not documented for users.

## Examples

- "Invoice link customer ko bheja" → they open it in any browser, no app needed.
- "Supplier ko PO dikhana hai" → share the PO public link; they can view/print but not approve online.
- "Catalog scrape ho sakta hai kya?" → only visible products at public prices, and rate limits apply.

## Errors

- "Order not found" / "Catalog not found" / invoice or PO not found — wrong, expired, or regenerated link.
- "Too many requests, please try again later." — rate limit hit.
- Expired/cancelled collect-link — request a fresh payment link from the store.

## FAQ

**Q: Is there a developer/partner API with keys?** 
Not today — public endpoints only serve DragBizz's own share links. A partner API is not available yet.

**Q: Are public links secure?** 
Each uses an unguessable ID/token; treat a link like the document itself — anyone holding it can view.

**Q: Can a supplier approve a PO from the public link?** 
No — the link is view-only; approval happens inside the app.
