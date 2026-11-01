---
module: reports
feature: analytics-pages
version: 1
language: en
updated_at: 2026-07-23
status: partial
---

# Analytics Pages — What Each Shows

## Overview

Reference for every analytics page: the exact metrics each dashboard displays. All pages offer PDF/XLSX download; charts marked "Coming Soon" are not live yet.

## Daily Sales (`/dashboard/analytics/daily-sales`)

- Today's sales amount (₹), today's bill count, and today's profit (GST stores) or released-today count (non-GST).
- **Recent Bills Today** table (invoice, amount, status; up to 15 rows). Empty state: "No bills recorded today yet".
- Always shows today — no filters. Non-GST stores see a prompt to add GST; GST stores get a link to GST Analytics.

## Revenue (`/dashboard/analytics/revenue`)

- Cards: Total Revenue, Total Profit, Profit Margin, Today's Revenue (with % change vs the previous period).
- Revenue Breakdown: today's revenue/profit, 30-day totals for revenue, profit, discount, and GST.
- Figures are for the **last 30 days**, released invoices only. Trend/source charts: Coming Soon.

## Sales (`/dashboard/analytics/sales`)

- Cards: Total Invoices, Released, Draft, Cancelled (all-time counts).
- Sales Breakdown: today's invoices, total released amount, average order value.
- Trend/by-product charts: Coming Soon.

## Stock (`/dashboard/analytics/stock`)

- Cards: Total SKUs, Total Quantity, **Low Stock Items**, Out of Stock.
- Status cards: Available / Reserved / Sold stock. Value: Total Stock Value, Average Cost.
- Services are excluded (no stock). Charts: Coming Soon.

## Products (`/dashboard/analytics/products`)

- Cards: Total Products, Active, Inactive. Category/top-selling charts: Coming Soon.

## Customers (`/dashboard/analytics/customers`)

- Cards: Total Customers, Today's Customers, Last 7 Days, Last 30 Days (+ last 3 months in statistics).
- Growth/segment charts: Coming Soon.

## Suppliers (`/dashboard/analytics/suppliers`)

- Cards: Total Suppliers, Active, Inactive. Growth/performance charts: Coming Soon.

## Bills (`/dashboard/analytics/bills`)

- **Filters:** Date Range (All Time / Today / This Week / This Month [default] / Quarter / Year) + Supplier.
- Cards: Total / Paid / Pending / Overdue bills. Amounts: Total Payable, Total GST Paid, Total Paid, Total Due.
- Performance: Average Payment Time, On-Time Rate, Supplier Reliability. Lists: Top Suppliers, Monthly Bill Trends.

## Expenses (`/dashboard/analytics/expenses`)

- Cards: Total / Today / Paid / Pending expenses. Amounts: total, net, GST.
- **Live breakdowns** (working, not Coming Soon): by Category and by Payment Method (amount, count, share %).
- Note: the separate Expenses → Reports page is placeholder-only; use this page for real numbers.

## GST (`/dashboard/analytics/gst`)

- GST-registered stores with the Premium GST capability only. See the GST analytics documentation for details (net GST position, GSTR sections, health score, CA/Tally exports).

## Errors

- "Your plan does not include analytics…" / crown lock — analytics needs a plan with the reports/analytics capability.
- "No bills recorded today yet" (Daily Sales) and similar empty states — no data in the page's window yet.
- Zero/stale GST figures — select a specific month and run Sync Data on the GST Analytics page.

## FAQ

**Q: Which page answers "aaj ki sale kitni hai"?** 
Daily Sales — today's amount and bill count (the voice assistant's today-sale query uses the same numbers).

**Q: Where do I see my pending supplier dues?** 
Bill Analytics → Total Due, plus the Pending/Overdue bill counts.

**Q: Which analytics have working filters?** 
Bills (date range + supplier) and GST (year/month). The rest use fixed windows.
