---
module: dashboard
feature: expenses
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Expenses

## Overview

Track business expenses at `/dashboard/expenses`: rent, transport, staff wages, utilities, and more — with GST/ITC details, payment method, vendor, and payment status. Cash expenses marked Paid link into the cashbook automatically. Expense creation requires a plan with the `expense` feature (not in the free Khata plan).

## Workflow

1. **Add** — **Add Expense** drawer: Title (required), Bill Number, Date (default today), Category (required — options include rent, daily expenses, transport, shop supplies, staff wages, utilities, office supplies, travel, marketing, promotions, legal, insurance, maintenance, cleaning, communication, training, miscellaneous), Amount (required), GST details (0/5/12/18/28%, tax-included toggle, RCM flag, ITC), Payment Method (Cash, Bank Transfer, UPI, Credit/Debit Card, Cheque, Net Banking), Vendor (optional, with GSTIN), Status (default Paid; also Pending/Overdue/Cancelled), Description.
2. **List** — search, date-range filter, table/card views, infinite scroll. Columns: title, date, category, amount, payment method, vendor, status.
3. **Edit / View / Delete** — from row actions; delete asks for confirmation (soft delete).
4. **Download** — export CSV/Excel/PDF for a period (1/3/6/12 months or custom) with selectable fields and sorting.
5. **Analytics** — real numbers at Analytics → Expense Analytics (totals, by category, by payment method). The "Reports" page under Expenses is placeholder-only.

## Business rules

- Title, date, category, amount, and payment method are required; amount must be greater than 0.
- Cash + Paid expenses auto-create a cashbook Cash Out entry (a hint appears in the form); changing status/method reverses it.
- GST on expenses feeds ITC figures in GST analytics and exports.
- Deleted expenses are removed from lists and analytics but recoverable by support (soft delete).
- Staff need `expense` permissions; creation counts against the plan's expense quota (e.g., 150/month on the Startup plan).

## Examples

- "Record ₹15,000 shop rent paid by bank transfer" → Add Expense → title Rent → category rent → amount → Bank Transfer → Paid.
- "How much did I spend on transport this quarter?" → Expense Analytics → by Category, or Download with a custom range.
- "Add a pending electricity bill" → status Pending; mark Paid when settled (cash ones then hit the cashbook).

## Errors

- Field validation — title/amount/date/category/payment method required.
- `Quota exceeded` / daily limit — plan's expense quota reached; upgrade needed.
- `This feature (expense) is not available in your current plan.` — free plan; expenses need a paid plan.
- Download errors — select a time period; end date must be after start; "No expenses found to download".

## FAQ

**Q: Which expenses show in the cashbook?** 
Only cash-mode expenses with status Paid. Bank/UPI/card expenses never touch the cashbook.

**Q: Can I claim GST input credit on expenses?** 
Enter the GST details (rate, ITC claimable) — they flow into GST analytics and the CA export.

**Q: Are recurring expenses supported?** 
No — each expense is entered individually.
