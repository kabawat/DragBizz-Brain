---
module: inventory
feature: stock
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Stock & Batches (FIFO)

## Overview

Stock is tracked per product in **batches**: each Stock In creates a batch with quantity, purchase price, optional supplier, and optional expiry date. Sales deduct stock **FIFO** (oldest batch first) when invoices are released; cancellations and credit notes restore it. The Stocks screen (`/dashboard/stock`) requires the **FIFO capability** (Premium ERP plan).

## Workflow

1. **Stock In** — from Stocks → **Add Stock**, or a product row → **Stock In**. Enter Quantity and Purchase Price (per unit), optionally Supplier; the summary shows total value and the new stock level. A batch number is generated automatically (you never type one).
2. **View stock** — the list shows each product's available/total quantity, status badge (Active / Low Stock / Out of Stock), batch counts, and average selling/cost pricing. The stock view page lists batch details: batch number, quantity, purchase price, supplier, expiry, status.
3. **Automatic movements** — releasing an invoice deducts stock FIFO from active, non-expired batches; cancelling an invoice or issuing a credit note restores it to the original batches. Every movement is recorded as a stock transaction (added / deducted / adjusted / returned).
4. **Corrections** — edit a batch's quantity/price from stock edit. A batch can be deleted only when its quantity is zero. Deleting an inventory record removes the product's batches entirely.
5. **Expiry** — batches with expiry dates are excluded from sale once expired; categories can enforce mandatory expiry dates.

## Business rules

- Stock In requires quantity > 0 and purchase price ≥ 0; expiry date cannot be in the past.
- FIFO order: oldest received batch is consumed first; expired/inactive batches are skipped.
- Services never have stock; only goods are tracked.
- Insufficient stock in a batch blocks a manual deduction ("Insufficient stock. Available: X, Required: Y").
- Stock screens and mutations are gated by the `fifo` capability: "FIFO inventory depth requires Premium ERP. Upgrade to manage stock batches."
- Customer returns restore stock through **credit notes** on the invoice; a standalone stock-out/return screen is not part of the current app UI (return APIs exist for desktop/sync use).
- Staff need `inventory` permissions; stock deductions/additions from billing follow the invoice permissions.

## Examples

- "Received 50 units of Sugar at ₹42 from Gupta Traders" → Stocks → Add Stock → select product → 50 → 42 → supplier → save (new batch).
- "How much stock of Sugar is left?" → Stocks list, or ask the voice assistant for a stock summary.
- "Customer returned 2 units" → open the released invoice → issue a partial credit note for that line; stock is restored automatically.

## Errors

- `Quantity must be greater than 0` / `Purchase price must be greater than 0` — form validation.
- `Expiry date cannot be in the past` — fix the batch expiry.
- `Cannot delete batch with remaining quantity. Please adjust quantity to 0 first.`
- `Insufficient stock. Available: X, Required: Y` — deduction larger than available.
- Plan/capability messages — FIFO requires Premium ERP; staff see "contact your Store Admin".

## FAQ

**Q: When does stock actually decrease for a sale?** 
When the invoice is **released** — drafts and carts never touch stock.

**Q: Can I choose which batch a sale consumes?** 
No — consumption is always FIFO (oldest active batch first); expired batches are skipped.

**Q: How do I record shop-use or damaged goods?** 
There is no standalone stock-out screen currently. Adjust the affected batch quantity from stock edit, or handle customer returns via credit notes.

**Q: What do the status badges mean?** 
Out of Stock = zero available; Low Stock = at or below the low-stock threshold (default 10); Active = healthy stock.
