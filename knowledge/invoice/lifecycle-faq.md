---
module: invoice
feature: lifecycle-faq
version: 1
language: en
updated_at: 2026-07-31
status: shipped
---

# Invoice Lifecycle FAQ

Companion to [Invoice Lifecycle](lifecycle.md) — errors and common questions only.

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
