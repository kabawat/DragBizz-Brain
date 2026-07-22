---
module: supplier
feature: management
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Supplier Management & Accounts

## Overview

Suppliers are managed at `/dashboard/suppliers`: add them one by one or in bulk, track their account summary (purchases, paid, due, bills), and view payment behavior. Each supplier automatically gets an **account** that tracks balances, payment terms, and credit limits. The supplier module requires a plan that includes the `supplier` feature.

## Workflow

1. **Add a supplier** — Suppliers → **Add Supplier** (drawer). Fields: Supplier Name (required), Agency, GST Number (with verify — auto-fills details), Phone, Email. The app asks for at least a phone or an email.
2. **Search & filter** — search by name; filter by Account Status (Active/Inactive/Suspended) and Risk Level (Low/Medium/High).
3. **Bulk upload** — download the template (CSV/XLSX/JSON), fill rows (name required; phone, email, address, gst_number, agency, and optional opening balances), upload (max 5MB, 1000 rows). Duplicates by phone/email are skipped, not failed.
4. **View** — the supplier page shows contact info plus **Account Details**: Total Purchases, Total Paid, Due Amount, Total Bills, Credit Limit, Available Credit, Payment Terms, Risk Level, On-Time Payment %, and more. PDF download available.
5. **Edit / Delete** — from the row menu or view page. Deleting deactivates the supplier (soft delete); their bills and payment history remain.
6. **Download list** — export suppliers (Excel/CSV/PDF) with selectable fields and time period (requires report permission).

## Business rules

- Only the name is strictly required; phone/email, when given, must be valid (Indian 10-digit mobile / valid email) and are unique per store.
- A supplier account is created automatically with each supplier; payment terms default to 30 days (options: COD, 7/15/30/45/60/90 days).
- **Credit limits are informational** — DragBizz tracks credit utilized and available credit but does not block bills or orders when the limit is exceeded.
- Account status values: Active, Suspended, Blocked, Inactive; risk levels Low → Critical are tracked from payment behavior.
- Deleting a supplier does not delete bills, payments, or purchase orders.
- A merge operation exists in the backend API (moves bills, payments, and purchase orders to the primary supplier and deactivates the duplicate) but there is **no merge screen in the app UI**. Merge does not move account records.
- Staff need `supplier` module permissions; creation counts against the plan's supplier quota.

## Examples

- "Add supplier Gupta Traders with GSTIN" → Add Supplier → name + GST Number → Verify → save.
- "How much do I owe Gupta Traders?" → open the supplier → Account Details → Due Amount.
- "Import my supplier list from Excel" → Bulk Upload → template → fill → upload.

## Errors

- `Supplier already exists with same phone or email` — duplicate contact in this store.
- `Phone number must be 10 digits starting with 6-9` / `Invalid email format` / `Invalid GST number`.
- `File exceeds the maximum allowed rows (1000)` and file type/size errors on bulk upload.
- Plan errors — `This feature (supplier) is not available in your current plan.` or quota reached; upgrade required.
- `Access denied. You do not have '...' permission for supplier.` — staff permission missing.

## FAQ

**Q: What does "Available Credit" mean on the supplier page?** 
Credit Limit minus what you currently owe. It is a tracking aid only — purchases are not blocked when exceeded.

**Q: Can I restore a deleted supplier?** 
Deletion is a deactivation; their history stays. Contact support to reactivate, or re-add them.

**Q: Do bulk-uploaded suppliers get accounts too?** 
Yes — accounts are created automatically, including opening balances if your file has them.
