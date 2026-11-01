---
module: invoice
feature: lifecycle
version: 1
language: en
updated_at: 2026-07-31
status: shipped
---

# Invoice Lifecycle

## Overview

A DragBizz invoice moves through a fixed lifecycle: **Draft → Released → (Cancelled or Credit Note)**. Creating an invoice always produces a draft first; releasing finalizes it and deducts stock. Statuses are: `DRAFT`, `PENDING_PAYMENT` (awaiting online payment), `RELEASED`, `CANCELLED`, `DELETED`. Invoice types are `REGULAR` and `CREDIT_NOTE`.

## Workflow

1. **Create draft** — open Invoices (**Alt+I**), then Create Invoice (**Shift+N**) — or go to Invoices → Create Invoice (`/dashboard/invoices/create`), or use POS (**Alt+K**). Add line items (product + quantity), optional customer (defaults to walk-in), optional total discount in ₹. Invoice number is assigned at creation. Save with **Ctrl+S** or **F1**.
2. **Edit draft** — only `DRAFT` invoices can be edited (`/dashboard/invoices/[id]/edit`; **Ctrl+E** from the list/view). Editing recalculates totals and resets payment status to `UNPAID`.
3. **Release** — from the invoice list, view page, or the payment modal shown right after creation. Releasing finalizes the invoice: it cannot be edited afterwards. Stock is deducted FIFO for goods; service items skip stock. You can release as PAID, PARTIAL, or UNPAID.
4. **Online payment path** — if the customer pays online, the draft moves to `PENDING_PAYMENT` while the payment order is active; a successful payment releases it automatically as `PAID`. Stale payment orders (about 30 minutes) revert the invoice to `DRAFT`.
5. **Cancel** — only `RELEASED` invoices can be cancelled. Cancelling restores stock from the invoice's recorded batches and reverses khata (customer account) entries. The invoice stays in the system with status `CANCELLED`.
6. **Credit note** — issued against a `RELEASED` regular invoice, full or partial (selected lines/quantities). Creates a new document of type `CREDIT_NOTE` with a CRN number and restores stock for the credited quantities. The original invoice is unchanged. Only one credit note per invoice.
7. **Delete** — only `DRAFT` invoices can be deleted.

## Business rules

- Only `DRAFT` invoices can be edited or deleted.
- Only `RELEASED` invoices can be cancelled or receive a credit note.
- One credit note per original invoice; credit notes only against `REGULAR` released invoices.
- Releasing requires the **POS capability** on your subscription. The free/Khata plan allows drafts only (up to 30 per day); releasing needs Premium ERP.
- Max 1000 line items per invoice; no duplicate products; quantity must be at least 1.
- Releasing as PAID with a paid amount lower than the total applies a settlement discount and rewrites totals.
- Staff need the matching `invoice` permission (create/edit/delete); store owners have full access.

## Examples

- "Jaldi naya invoice" → **Alt+I** then **Shift+N** (Invoices → Create Invoice).
- "Create a bill for 2 units of Sugar 1kg for walk-in customer" → creates a draft; the payment modal then lets you collect and release.
- "Why can't I edit this invoice?" → it is already `RELEASED`; only drafts are editable. Issue a credit note or cancel it instead.
- "Return one item from a released invoice" → create a **partial credit note** selecting that line and quantity.

Errors and FAQ: see [Invoice Lifecycle FAQ](lifecycle-faq.md).
