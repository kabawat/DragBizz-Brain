---
module: reports
feature: analytics-overview
version: 1
language: en
updated_at: 2026-07-23
status: partial
---

# Analytics Overview & Plan Access

## Overview

The Analytics menu gives per-area dashboards: Daily Sales, Revenue, Sales, Stock, Product, Customer, Supplier, Bill, and Expense analytics — plus GST Analytics for GST-registered stores. Each page shows metric cards and breakdowns with PDF/XLSX report downloads. Analytics is a paid-plan capability; locked items show a crown icon.

## Workflow

1. Open **Analytics** in the sidebar and pick an area (e.g. `/dashboard/analytics/revenue`).
2. Read the metric cards; most pages show fixed windows (today + last 30 days) rather than custom date pickers. **Bill Analytics** is the exception with a date-range filter (Today / This Week / This Month / Quarter / Year / All Time) and a supplier filter.
3. Download a report — the floating **Download Report** button exports PDF or XLSX on every page.
4. GST stores also see **GST Analytics** (see the GST docs) with year/month selection and CA/Tally exports.

## Business rules

- **Plan gate:** each analytics item requires the Analytics capability on that module's subscription feature. Locked items show a crown and an upgrade prompt: "Your current plan does not include Analytics for the ... module...". Staff on gated features are told to contact the Store Admin.
- **Data freshness:** summary numbers come from pre-aggregated statistics refreshed within ~5–15 minutes of activity (and on view). Figures can lag a few minutes behind the latest sale.
- Revenue/profit figures count **released invoices only** — drafts and cancelled invoices are excluded from revenue.
- **Charts are not live yet:** the trend/segment chart widgets on Revenue, Sales, Stock, Products, Customers, and Suppliers pages show "Coming Soon". The numbers, tables, and breakdown lists are real.
- The Expense **Reports** page under Expenses (`/dashboard/expenses/reports`) is placeholder-only ("Advanced analytics coming soon") — real expense numbers live at `/dashboard/analytics/expenses`.
- Staff access requires the analytics permission for the relevant module; store owners always have access.

## Examples

- "How is my business doing this month?" → Revenue Analytics (30-day revenue/profit/margin) + Daily Sales for today.
- "Show supplier bill dues for this quarter" → Bill Analytics → Date Range: This Quarter.
- "Why does Analytics show a crown?" → your plan lacks the Analytics capability for that module — upgrade or ask the owner.

## Errors

- "Your current plan does not include Analytics for the ... module..." — plan gate; upgrade required.
- "Plan Restricted" screen on direct URL access without the plan capability.
- `Access denied. You do not have 'analytics' permission for ...` — staff permission missing.
- Zeros everywhere — usually no data yet for the store, or stats still syncing; revisit after a few minutes.

## FAQ

**Q: Can I pick a custom date range?** 
Only Bill Analytics (and GST Analytics) have period filters today; other pages use fixed windows (today / last 30 days / rolling periods).

**Q: Why don't my draft invoices show in revenue?** 
Revenue counts only released invoices. Release the invoice for it to count.

**Q: Where are the graphs?** 
Chart widgets are marked Coming Soon; use the metric cards and breakdown tables, or export XLSX for your own charts.

**Q: Is analytics real-time?** 
Near real-time — summaries refresh within minutes of activity.
