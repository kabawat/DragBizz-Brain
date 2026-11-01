---
module: invoice
feature: pos
version: 1
language: en
updated_at: 2026-07-22
status: shipped
---

# Point of Sale (POS)

## Overview

The POS screen (`/dashboard/pos`) is a fast checkout counter: search products, build a cart, and collect payment. Every POS checkout creates a draft invoice (order source `POS`, walk-in customer) and immediately opens the Collect Payment modal to release it. POS requires the **POS capability** (Premium ERP plan).

## Workflow

1. **Find products** — search by name or SKU, filter by category, browse grid or list. Shortcut: `/` or Ctrl+K focuses search.
2. **Build cart** — tap products to add; adjust quantity with +/−; remove items. A cart-level **Discount (₹)** is applied to the invoice.
3. **Checkout** — press **Collect ₹X** (or Ctrl+Enter). This creates a draft invoice and opens the Collect Payment modal.
4. **Collect payment** — choose Cash, UPI (QR), Card, or Online (customer display). Confirm to release as paid, or release as unpaid.
5. **After payment** — the invoice opens with auto-print, then returns to POS for the next sale. Ctrl+Delete clears the cart.

## Business rules

- POS is gated by the `pos` capability on the invoice module. Free/Khata plans see: "POS and invoice release require Premium ERP. Upgrade to unlock full billing."
- POS sales are recorded as walk-in with order source `POS`.
- The cart-level ₹ discount is applied to the invoice. The per-item % discount shown in the cart and the typed customer name are display aids only — they are not saved on the invoice (current limitation).
- Barcode scanning is available on the invoice create page, not on the POS screen.
- Staff need `invoice` create permission to use POS.

## Examples

- "Bill 3 Parle-G and 1 Milk 500ml, cash" → add items → Collect → Cash → Release Invoice → auto-print.
- "Give ₹20 off on the whole bill" → set cart Discount ₹20 before Collect.
- "Show the payment QR to the customer" → use the **Display** button to open the customer payment screen, or choose UPI in the collect modal.

## Errors

- Plan lock message ("...require Premium ERP...") — subscription lacks the POS capability; staff members are told to contact the Store Admin.
- Empty cart — "Your cart is empty. Pick products from the menu..." — add items before checkout.
- Product search empty state — no products match; check spelling or category.
- Quota exceeded on invoice creation — daily invoice limit reached on your plan.

## FAQ

**Q: Does POS deduct stock immediately?** 
Stock is deducted when the invoice is **released** (i.e., when you confirm payment in the collect modal), not when items are added to the cart.

**Q: Can I attach a customer to a POS sale?** 
POS checkouts are walk-in. To bill a saved customer (for khata/udhari), create the invoice from Invoices → Create Invoice instead.

**Q: Why don't my item-level % discounts appear on the invoice?** 
Currently only the cart-level ₹ discount is sent to the invoice. Item % discounts in the POS cart are visual only.
