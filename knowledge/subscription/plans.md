---
module: subscription
feature: plans
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Plans & What's Included

## Overview

DragBizz has a free **Khata Free** tier plus paid plans. Every new account starts on Khata Free automatically — unlimited customers, khata, cashbook, and payment reminders, with up to 30 draft invoices per day. Paid plans unlock the full ERP: invoice release/POS, inventory, suppliers, expenses, staff, reports, AI, and more. See your current plan at **Management → Subscription** (`/dashboard/management/subscription`).

## Plan catalog

| Plan | Price (INR) | Highlights |
|---|---|---|
| **Khata Free** | ₹0 | Unlimited customers, khata, cashbook, payment reminders; 30 draft invoices/day; 50 products; 1 store. Everything else locked. |
| **Startup** | ₹49/mo | 30/day invoices, customers, sales orders; 150 expenses/month; unlimited inventory; no staff. |
| **Basic** | ₹499/mo (₹2,695/6mo, ₹4,790/yr) | Most modules unlimited; 500 products; 2 staff; 1 store; 1 online store; GST reports. No AI. |
| **Standard** | ₹999/mo (₹5,095/6mo, ₹8,991/yr) | 2 stores; 1,000 products; 5 staff; 2 online stores; 100 AI queries/month; GST + sales summary reports. |
| **Premium** | ₹1,999/mo (₹9,595/6mo, ₹16,791/yr) | 5 stores; unlimited products, staff, AI; POS + invoice release; FIFO inventory with batches and stock events; full reports. |

Prices are seed/list values; the live catalog on the Pricing page is authoritative. Multi-month pricing gives discounts; GST applies on top.

## Feature gates

Each plan lists features per module: `billing`, `invoice`, `product`, `inventory`, `customer`, `supplier`, `expense`, `cashbook`, `purchase_order`, `sales_order`, `staff`, `reports`, `store`, `ai`, `online_store`, `customer_payment_gateway`, `payment_reminder`, `integrations`. Some modules also carry **capabilities** (e.g., invoice `draft`/`release`/`pos`; inventory `fifo`/`batches`/`stock_events`; reports `gst`/`sales_summary`/Tally). If your plan lacks a module or capability you'll see a message like "This feature (expense) is not available in your current plan" or "Your plan does not include gst for reports. Please upgrade to Premium ERP."

## The Subscription page

- Shows your plan name, status badge, start date, and rate.
- **Khata Free** users see the free-plan card (unlimited khata, reminders, cashbook; 30 invoices/day) with an **Upgrade to Premium ERP** button that opens the Pricing page.
- **Included Services** lists up to 8 unlocked modules with short descriptions.
- No subscription at all shows "No Active Plan" with an upgrade prompt.

## Business rules

- Khata Free is provisioned automatically (long-running trial); no payment needed.
- Free-tier invoices are **draft only** — releasing an invoice (making it final/POS) needs a paid plan with the `release`/`pos` capability.
- Only the **store owner** can buy or change subscriptions; staff cannot.
- You can't re-purchase a package you already have active — renewal opens closer to expiry.

## Examples

- "Kya main free plan par invoice bana sakta hoon?" → Yes, up to 30 drafts/day, but you can't release them — that needs a paid plan.
- "Staff add karna hai" → Basic (2 staff), Standard (5), or Premium (unlimited).
- "AI assistant kaunse plan mein hai?" → Standard (100 queries/month) or Premium (unlimited).

## Errors

- `No active subscription found. Please upgrade your plan.`
- `This feature ({module}) is not available in your current plan.`
- `Your plan does not include {capability} for {module}. Please upgrade to Premium ERP.`
- `Access Denied: Only store owners can purchase or modify subscriptions.`
- `You already have an active subscription for this package...` — wait until near expiry to renew.

## FAQ

**Q: What stays free forever?** 
The khata core: unlimited customers, khata entries, cashbook, and payment reminders.

**Q: Why can't I release/print a final invoice on the free plan?** 
Free invoices are drafts only. Upgrade to a plan with invoice release.

**Q: Does upgrading keep my data?** 
Yes — plans only change limits and unlocked modules; your data is untouched.
