---
module: gst
feature: analytics
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# GST Analytics, Mismatches & Health Score

## Overview

GST Analytics (`/dashboard/analytics/gst`) gives GST-registered stores a CA-ready view of their tax position: output GST from sales, input tax credit (ITC) from purchase bills, mismatch checks, and a GST health score. The page appears in the sidebar only when your store has a GST number, and requires a plan with GST reports (Premium).

## Workflow

1. **Pick a period** — select Year and **Month** at the top. Detailed figures come from monthly statistics, so choose a specific month for full data.
2. **Sync Data** — with a month selected, press Sync Data to recompute that month's GST statistics from your released invoices, bills, and expenses.
3. **Read the cards**:
   - **Net GST Position** — output GST minus input GST ("Tax Payable" or "Tax Credit Available").
   - **Total GST Collected** — from released invoices (with invoice count).
   - **Total ITC Claimed** — from purchase bills (with bill count).
   - **Total Taxable Sales** — the sales base.
4. **Breakdowns** — Outward Supplies (GSTR-1 section): taxable value, B2B vs B2C sales, CGST/SGST/IGST distribution, HSN coverage %. Inward Supplies (GSTR-2B section): taxable value, ITC-eligible vs non-ITC purchases, ITC breakdown.
5. **Mismatches** — a read-only list of detected issues (up to 20 shown) with invoice number and product.
6. **Health score** — a 0–100 score with color bands; 80+ earns the "GST-safe shop" badge.
7. Export buttons — **Export for CA** and **Export to Tally** (see their docs).

## Business rules

- Visibility: store must have a GST number; plans need the `gst` reports capability ("GST analytics require Premium ERP...").
- **Mismatch types detected** (invoices only):
  - *Calculation mismatch* — GST collected by a composition/unregistered store (high severity), or the stored GST differs from rate × taxable by more than ₹0.05 (medium).
  - *Missing HSN* — a taxed line item without an HSN code (low severity).
- **Health score formula**: starts at 100; loses up to 30 points for HSN coverage gaps, 5 points per mismatch (max 40), and up to 20 points for months without data. Bands: 80+ green (GST-safe shop), 60–79 warning, below 60 danger. Scored per calendar year.
- The mismatch list is informational — fix issues by editing the product's HSN or reviewing the invoice; there are no inline fix buttons.
- B2B sales are those to customers with a saved GSTIN.

## Examples

- "How much GST do I owe for June?" → GST Analytics → Year + June → Net GST Position.
- "Why is my health score low?" → check the breakdown: HSN coverage %, mismatch count, period coverage — add missing HSN codes and sync each month's data.
- "My numbers look stale" → select the month → Sync Data.

## Errors

- `Your plan does not include gst for reports. Please upgrade to Premium ERP.` — plan gate.
- Sidebar item missing — the store has no GST number; add it in Settings → Store (the Daily Sales page shows an "Add GST" prompt too).
- `Year and Month are required for sync` — pick a month before syncing.
- "No GST mismatches found. Your data looks compliant." — clean state, not an error.

## FAQ

**Q: Why are my totals zero?** 
Select a specific month (not "All months") and run Sync Data — figures are built from monthly statistics.

**Q: Does the mismatch check look at purchases?** 
No, only released sales invoices. Purchase-side data feeds ITC totals but is not mismatch-scanned.

**Q: What makes a "GST-safe shop"?** 
Health score 80+: good HSN coverage on taxed items, few or no mismatches, and data present across the year's months.

**Q: I'm on the Khata Free plan — can I see GST analytics?** 
No — GST reports need a paid plan with the GST capability.
