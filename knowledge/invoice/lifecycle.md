---
module: invoice
feature: lifecycle
version: 1
language: en
updated_at: 2026-07-22
status: shipped
---

# Invoice Lifecycle

## Overview

A DragBizz invoice moves through a fixed lifecycle: **Draft → Released → (Cancelled or Credit Note)**. Creating an invoice always produces a draft first; releasing finalizes it and deducts stock. Statuses are: `DRAFT`, `PENDING_PAYMENT` (awaiting online payment), `RELEASED`, `CANCELLED`, `DELETED`. Invoice types are `REGULAR` and `CREDIT_NOTE`.

## Workflow

1. **Create draft** — from Invoices → Create Invoice (`/dashboard/invoices/create`) or POS checkout. Add line items (product + quantity), optional customer (defaults to walk-in), optional total discount in ₹. The invoice number is assigned at creation. Keyboard: Ctrl+S or F1 to save.
2. **Edit draft** — only `DRAFT` invoices can be edited (`/dashboard/invoices/[id]/edit`). Editing recalculates totals and resets payment status to `UNPAID`.
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

- "Create a bill for 2 units of Sugar 1kg for walk-in customer" → creates a draft; the payment modal then lets you collect and release.
- "Why can't I edit this invoice?" → it is already `RELEASED`; only drafts are editable. Issue a credit note or cancel it instead.
- "Return one item from a released invoice" → create a **partial credit note** selecting that line and quantity.

## Errors

- `Cannot update invoice with status: RELEASED. Only DRAFT invoices can be updated.` — edit attempted on a non-draft.
- `Only released invoices can be cancelled` — cancel attempted on draft/cancelled invoice.
- `A credit note already exists for this invoice` — one credit note limit.
- `Your plan does not include pos for invoice. Please upgrade to Premium ERP.` — release blocked on free plan.
- `QUOTA_EXCEEDED` / daily limit reached — draft creation limit hit (30/day on free plan).
- `No batch information found for stock restoration` — cancel/credit note cannot restore stock because the release did not record batches.
- `Access denied. You do not have '...' permission for invoice.` — staff permission missing.

## FAQ

**Q: Does creating an invoice reduce my stock?** 
No. Stock is deducted only on **release**, and only for goods (services never touch stock).

**Q: Can I undo a release?** 
You cannot revert to draft. Cancel the invoice (restores stock) or issue a credit note for returns.

**Q: When is the invoice number assigned?** 
At draft creation, using your store's invoice number format.

**Q: What is PENDING_PAYMENT?** 
The invoice is waiting for an online payment. It cannot be released manually in this state; it releases automatically when payment succeeds, or reverts to draft if the payment order expires.
