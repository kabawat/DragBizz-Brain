---
module: sales-order
feature: management
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Managing Sales Orders (Store Side)

## Overview

Orders from your public catalog (online and in-store QR) arrive at **Sales Orders** (`/dashboard/sales-order`). From the list you filter by source and status; from the order detail you move it through its lifecycle — Confirm, Process, **Ship (which automatically generates and releases the invoice)**, deliver, mark paid, or cancel.

## Workflow

1. **List** — search, filter by source (All / Online / In-Store) and status (Pending, Confirmed, Processing, Shipped, Delivered, Cancelled), date range, table/card views. The Public Catalog QR button is also here.
2. **Order detail** — customer & shipping info, items, activity history (every status change is logged), notes.
3. **Status workflow** — action buttons follow the flow: **Confirm** or **Decline** a pending order → **Processing** → **Shipped** (add tracking number / courier partner) → In Transit → Out for Delivery → **Delivered**. Plus **Mark as Paid** and **Cancel**.
4. **In-store orders** use friendlier labels: shipped-family statuses show as **Order Ready** and delivered as **Served**.

## Business rules

- **Marking an order Shipped creates and releases an invoice automatically** — stock is deducted (FIFO) and the sale enters your books; success message: "Order marked as shipped and invoice generated."
- You cannot ship an order that is Cancelled, Returned, or already Delivered.
- Payment status (Unpaid / Paid / Partially Paid) syncs with the generated invoice; payment modes: Cash, Card, UPI, Wallet, Online.
- Staff need `sales_order` permissions (read to view, edit to change status).
- New public orders start as Pending/Unpaid — nothing hits stock or books until you ship.
- There is no separate "convert to invoice" button — shipping *is* the conversion.

## Examples

- "Naya online order aaya" → open it → Confirm → Processing → Shipped (tracking no.) → invoice ban gaya, stock cut gaya.
- "Table 4 ka order ready hai" → in-store order → Order Ready → Served.
- "Customer ne cancel bola" → order → Cancel (before shipping; after shipping handle it via credit note on the invoice).

## Errors

- "Cannot ship order with status: …" — the order is in a terminal state.
- "Access denied. You do not have 'edit' permission for sales_order." — staff permission missing.
- "Order not found" — deleted/wrong link.
- "Invalid status value".

## FAQ

**Q: When does stock get deducted?** 
Only when you mark the order Shipped — that releases the auto-generated invoice, which deducts stock FIFO.

**Q: What if the customer returns a shipped order?** 
Handle it on the generated invoice with a credit note (restocks the items); the order can be marked Returned.

**Q: Do declined orders affect anything?** 
No — declining/cancelling a pending order never touches stock or accounts.
