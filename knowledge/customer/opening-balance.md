---
module: customer
feature: opening-balance
version: 1
language: en
updated_at: 2026-07-22
status: shipped
---

# Opening Balance Import (Udhari)

## Overview

When you move to DragBizz from a paper khata or another app, you can import each customer's existing dues (udhari) in one go. The import matches rows to **existing customers by phone number** and creates an Opening Balance entry in their khata. Find it at Customers → Import → **Import Opening Balance**.

## Workflow

1. Make sure the customers already exist in DragBizz (add them manually or via Bulk Upload first).
2. Customers → Import → **Import Opening Balance**.
3. Download the sample template (`opening_balance_import_template.xlsx`; Excel/CSV/JSON supported).
4. Fill the required columns: **phone** and **openingDue** (aliases accepted: opening_due, total_due, udhari, due). Optional: name, notes.
5. Upload (max 5MB, up to 1000 rows). Results show **Imported / Skipped / Failed** with row-level reasons and a downloadable errors CSV.

Alternatively, the customer **Bulk Upload** template also accepts an opening due column — new customers can be created with their udhari in one step.

## Business rules

- Match is by phone number (normalized to 10-digit Indian mobile).
- `openingDue` must be **greater than 0** — advances or zero balances cannot be imported this way.
- One-time per customer: if the customer already has **any** khata entry, the row fails with `REOPENING_NOT_ALLOWED`. Opening balance is only for fresh khatas.
- Rows already imported earlier are skipped (`ALREADY_IMPORTED`); duplicate phones within the file are skipped (`DUPLICATE_IN_FILE`).
- The entry appears in the khata as an Opening Balance (You Gave side) and sets the starting due.
- Requires `customer` create permission.

## Examples

- "Import udhari from my old khata book" → create/verify customers → Import Opening Balance → template with phone + openingDue → upload.
- Row `9876543210, 1500` → Ramesh's khata starts with ₹1500 due.

## Errors

- `CUSTOMER_NOT_FOUND` — no customer with that phone; add the customer first.
- `REOPENING_NOT_ALLOWED` — the customer already has khata entries; record an adjustment instead.
- `ALREADY_IMPORTED` — opening balance was already imported for this customer.
- `DUPLICATE_IN_FILE` — the same phone appears twice in your file.
- Invalid file type / file too large (5MB) / too many rows (1000) — fix the file and retry.

## FAQ

**Q: Can I import advances (money I owe the customer)?** 
No — the import only accepts dues greater than 0. Record an advance manually as a You Got entry.

**Q: What if a customer's opening balance was wrong?** 
Delete the opening balance entry from their khata (it is a manual-type entry) and re-import, or add an adjustment entry.

**Q: Do I need to import all customers at once?** 
No. You can run the import multiple times; already-imported customers are skipped safely.
