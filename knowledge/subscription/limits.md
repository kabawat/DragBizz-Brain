---
module: subscription
feature: limits
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Plan Usage & Limits

## Overview

**Management → Plan Limits** (`/dashboard/management/limits`) shows how much of each module's quota you've used. Each row shows the module, used vs. limit, a progress bar (or "Unlimited" / "Not Included"), and a Details view with remaining quota and quota policy. Rows over 80% utilization are flagged as at risk, with "Boost Limits" / "Unlock Feature" buttons leading to the Pricing page.

## How quotas work

Limits come in five flavors:

- **Unlimited** — no cap.
- **Daily** (e.g., 30 invoices/day on free and Startup plans) — resets every day.
- **Monthly** (e.g., 150 expenses/month on Startup; 100 AI queries/month on Standard) — resets each month.
- **Total** (e.g., 50 products on Khata Free, 2 staff on Basic, stores per plan) — a running count; deleting frees capacity for count-based modules like products/staff/stores.
- **Not included (limit 0)** — the module is locked on your plan.

Usage counts when you create the item (invoice, expense, customer, etc.). The limits page also notes a periodic reset cycle in its footer.

## Khata Free limits (default plan)

| Module | Limit |
|---|---|
| Customers, cashbook, payment reminders | Unlimited |
| Invoices | 30 per day, **draft only** |
| Products | 50 total |
| Stores | 1 |
| Inventory, suppliers, expenses, staff, purchase orders, sales orders, billing, reports, online store, AI | Not included |

## Business rules

- When a quota is hit you get: "You have reached your {daily/monthly/total} limit of {N} for {module}. Please upgrade your plan for more capacity." (error code `QUOTA_EXCEEDED`).
- Modules with limit 0 are blocked at the first attempt with "This feature ... is not available in your current plan."
- Capability checks are separate from quotas — e.g., a plan may include `reports` but not the `gst` report capability.
- Usage displayed is per agency (across your account), synced from live activity.

## Examples

- "Kitne invoice bache hain aaj?" → Plan Limits → Invoice row → Used/limit for today.
- "Product limit full ho gaya" → free plan caps 50 products; delete unused products or upgrade.
- "Expense add nahi ho raha" → on Khata Free the expense module is Not Included; on Startup check the 150/month quota.

## Errors

- `QUOTA_EXCEEDED` — daily/monthly/total limit reached; upgrade for more capacity.
- `FEATURE_NOT_AVAILABLE` — module not in plan.
- "This feature is not part of your current plan." — shown in the limit details modal.

## FAQ

**Q: When do daily and monthly limits reset?** 
Daily limits reset each calendar day; monthly limits reset each calendar month.

**Q: If I delete a product, do I get the slot back?** 
Yes — total-count limits like products, staff, and stores track the live count.

**Q: Do drafts count against the invoice limit?** 
Yes — each invoice created counts toward the daily limit, drafts included.
