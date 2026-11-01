---
module: gst
feature: ca-export
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# GST Export for CA Filing

## Overview

The **Export for CA** button on GST Analytics downloads a filing-ready workbook your chartered accountant can use for GSTR preparation: B2B/B2C sales, credit notes, ITC sheets, HSN-wise and rate-wise summaries. Choose Excel (multi-sheet, GSTR-2B style) or CSV.

## Workflow

1. GST Analytics → **Export for CA**.
2. In the drawer set: **Year** (financial-year start — e.g. 2024 means Apr 2024–Mar 2025), optional **Month**, optional **Quarter** (Q1 Apr–Jun … Q4 Jan–Mar, Indian FY).
3. Pick the format: **XLSX (Excel)** (default) or **CSV**.
4. Press **Download** — the file is generated in your browser (e.g. `gst-export-2026-07-23.xlsx`).

## Business rules

- The Excel workbook contains GSTR-2B-style sheets: ReadMe, ITC Available / Not Available / Reversal / Rejected, B2B, CDNR (credit/debit notes), IMPG, and more, plus HSN-wise and tax-rate-wise summaries.
- The CSV option exports the GSTR-1 rows (falling back to the HSN summary).
- Data comes from your released invoices, purchase bills, and expenses for the chosen period — keep monthly Sync Data up to date first.
- Requires the same plan gate as GST Analytics (`gst` reports capability) and a GST-registered store.
- Row details include GSTINs, invoice/bill numbers, dates, taxable values, CGST/SGST/IGST/cess, rates, HSN codes, place of supply, and ITC availability flags.

## Examples

- "Send my CA the Q1 GST data" → Export for CA → Year + Quarter Q1 → XLSX → Download → share the file.
- "I need June's GSTR-1 rows as CSV" → Year + Month June → CSV → Download.

## Errors

- "Failed to fetch export data" / "Export failed. Please try again." — retry; check connectivity.
- "No data to export" — the chosen period has no GST records; sync the month first.
- Plan gate errors — GST reports capability required.

## FAQ

**Q: Is this a direct GSTR filing?** 
No — it's a preparation export for your CA. Filing happens on the GST portal.

**Q: Why does my CA see missing invoices?** 
Only **released** invoices are included; drafts are excluded. Also run Sync Data for each month.

**Q: What period does "Year" cover?** 
The Indian financial year starting that April (2024 = Apr 2024 – Mar 2025). Month/Quarter narrow it further.
