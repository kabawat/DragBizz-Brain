---
module: gst
feature: tally-export
version: 1
language: en
updated_at: 2026-07-23
status: partial
---

# Tally Export & Ledger Mapping

## Overview

DragBizz can export your business vouchers as **Tally XML** for import into Tally Prime — sales invoices, credit notes, customer payment receipts, expense payments, and manual cashbook entries. Set it up once at Integrations → **Tally** (`/dashboard/integrations/tally`), then download XML from GST Analytics → **Export to Tally**.

## Workflow

1. **Enable** — Integrations → Tally → turn on **Enable Tally export** and enter the **Company Name** (must exactly match your company name in Tally Prime). Save.
2. **Ledger mapping (optional)** — the Advanced ledger mapping section lets you rename the target ledgers: Sales, Cash, Bank, Sundry Debtors/Creditors, Output & Input CGST/SGST/IGST, Purchase; per-payment-method ledgers (Cash/UPI/Bank Transfer/Cheque); and expense-category → ledger mappings (add via the modal). Defaults work out of the box.
3. **Export** — GST Analytics → **Export to Tally** → pick From/To dates (defaults: month start to today; maximum span 93 days) → **Download Tally XML** (`tally-export-{from}-{to}.xml`).
4. **Import in Tally Prime** — Gateway of Tally → Import → Vouchers → select the XML file.

## Business rules

- Exported voucher types: **Sales** and **Credit Note** (released invoices), **Receipt** (completed customer payments), **Payment** (paid expenses), **Contra** (manually added cashbook entries). Auto-generated cashbook entries are skipped to avoid duplicates.
- Date range is required and cannot exceed **93 days**; export repeatedly for longer periods.
- Tally export must be enabled first — the GST Analytics button redirects you to the settings page otherwise.
- Requires a plan with Tally reports capability and reports read permission for staff.
- **Current limitations (roadmap):**
  - Supplier bills / purchase vouchers are **not exported yet**.
  - Inter-state expense GST is exported as CGST+SGST (IGST split fix pending).
  - A scheduled auto-sync agent is planned but not live — exports are manual.

## Examples

- "Send July's books to Tally" → Export to Tally → 1 Jul to 31 Jul → Download XML → import in Tally Prime.
- "My CA uses different ledger names" → Integrations → Tally → Advanced ledger mapping → rename to match the CA's chart of accounts.

## Errors

- `Tally integration is not enabled for this store. Enable it in store settings.` — turn on the toggle first.
- Company name required — enabling without a company name is blocked.
- `Date range cannot exceed 93 days` / from must be before to / dates required.
- `Your plan does not include tally for reports. Please upgrade to Premium ERP.` — plan gate.

## FAQ

**Q: Do purchases/supplier bills go to Tally?** 
Not yet — purchase vouchers are on the roadmap. Export currently covers sales, credit notes, receipts, expense payments, and manual cashbook entries.

**Q: Why must the company name match Tally exactly?** 
Tally Prime imports vouchers into the company named in the XML; a mismatch makes the import fail or land in the wrong company.

**Q: Will the same voucher import twice if I export overlapping ranges?** 
The export dedupes within a file, but overlapping imports into Tally can duplicate — keep ranges non-overlapping.

**Q: Is there automatic syncing to Tally?** 
No — exports are manual XML downloads today; a scheduled sync agent is planned.
