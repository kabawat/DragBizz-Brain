---
module: customer
feature: management
version: 1
language: en
updated_at: 2026-07-22
status: shipped
---

# Customer Management

## Overview

Customers are managed from `/dashboard/customers`: add customers one by one, import them in bulk, search and filter the list, and view each customer's details and khata. Each customer needs a name plus at least one contact method (phone or email). Phone numbers are stored as 10-digit Indian mobile numbers.

## Workflow

1. **Add a customer** — Customers → **Add Customer** (side drawer). Fill Name (required) and Phone or Email (at least one required). Optionally add company details (Company Name, GSTIN with verify), and billing/shipping addresses. You can also add a customer on the fly from the invoice create page ("Add New Customer" in the customer dropdown).
2. **Search & filter** — search by name/phone/email; filter by Status (Active/Inactive), Source (Manual, POS, Invoice, Bulk Import, Online, In Store, WhatsApp, Phone, QR Catalog), **Balance** (Due / Advance / Both), and date range.
3. **Bulk upload** — Import → **Bulk Upload**. Download the template (Excel/CSV/JSON), fill rows, upload (max 5MB, up to 1000 rows). Columns: name, phone, email, company_name, gstin, gst_detail, and optional opening dues (total_due / opening_due / udhari). Results show Created / Skipped / Failed with row-level errors and an errors CSV download.
4. **Edit** — from the row menu or customer view; same form as add.
5. **Delete** — row menu → Delete with confirmation. Deletion is permanent.
6. **Download** — export the customer list (requires report permission; date range required, up to 10,000 rows).

## Business rules

- Name is required (2–100 characters); phone **or** email is required.
- Phone and email must be unique per store — duplicates are rejected.
- Phone is normalized to a 10-digit Indian mobile (starting 6–9); `+91`/leading 0 are stripped.
- If a GSTIN is entered it must be the 15-character format and include GST details.
- Bulk upload skips rows whose phone/email already exists (in the store or earlier in the file) — skips are not errors.
- Deleting a customer is a **hard delete** and is not blocked by existing invoices or khata entries — the history remains but the customer profile is gone. Delete carefully.
- The Balance filter works on loaded rows; with many customers the list keeps loading pages while searching for matches ("Looking for customers with balance...").
- Staff need `customer` module permissions (create/read/edit/delete); invoice permission also allows reading/creating customers during billing. Store owners have full access.
- A merge operation exists in the backend API (moves invoices, orders, and addresses to the primary customer and deactivates the duplicate) but there is **no merge screen in the app UI** currently. Merge does not move khata transactions or payments.

## Examples

- "Add customer Ramesh with phone 9876543210" → Add Customer → name + phone → Save.
- "Show customers who owe me money" → Balance filter → **Due**.
- "Import my 300 customers from Excel" → Import → Bulk Upload → download template → fill → upload.

## Errors

- `Customer already exists with same phone or email` — duplicate contact in this store.
- `Either Phone or Email is required` — no contact method given.
- `Please provide a valid phone number.` — phone fails validation.
- `File exceeds the maximum allowed rows (1000)` / file too large (5MB) / invalid file type — bulk upload limits.
- `Access denied. You do not have '...' permission for customer.` — staff permission missing.

## FAQ

**Q: Can I have two customers with the same phone number?** 
No — phone and email are unique per store.

**Q: What happens to a deleted customer's invoices?** 
Invoices and ledger history remain in the system, but the customer profile and addresses are permanently removed.

**Q: How do I merge duplicate customers?** 
There is no merge button in the app yet. The backend supports merging (invoices/orders/addresses move to the primary; khata entries do not) — contact support if you need it.

**Q: Where does the "Source" value come from?** 
It records how the customer entered the system: added manually, from POS/invoice, bulk import, online catalog, etc.
