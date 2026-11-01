---
module: faq
feature: common-errors
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Common Errors & What They Mean

## Overview

The most frequent error messages across DragBizz, what causes them, and how to fix them.

## Permission errors (staff accounts)

- **"Access denied. You do not have '{action}' permission for {module}."** — your role lacks that permission (e.g., delete on invoices). The store owner can grant it: Management → Staff → your card → Edit Permissions.
- **"Access denied. Your staff account is inactive or not found."** — your access was removed; contact the owner.
- **"Unauthorized - Only owner can access this resource"** — owner-only areas: stores, staff management, subscription, billing.

## Plan & quota errors

- **"This feature ({module}) is not available in your current plan."** (`FEATURE_NOT_AVAILABLE`) — the module has limit 0 on your plan (e.g., expenses/suppliers/staff on Khata Free). Upgrade from the Pricing page.
- **"You have reached your {daily/monthly/total} limit of {N} for {module}. Please upgrade your plan for more capacity."** (`QUOTA_EXCEEDED`) — daily limits reset next day, monthly next month; total limits (products/staff/stores) free up when you delete items.
- **"Your plan does not include {capability} for {module}. Please upgrade to Premium ERP."** — capability gates: invoice release/POS, inventory FIFO, GST/Tally reports.
- **"No active subscription found. Please upgrade your plan."** — the account has no plan record; re-login or contact support.

## GST issues

- **GST mismatches in GST Analytics** — flagged on released invoices: missing HSN codes on taxed items, or tax amounts that don't match the rate. Fix by adding the HSN on the product or reviewing the invoice, then re-run Sync Data for that month.
- **"Invalid GST format" / "Invalid PAN format"** — GSTIN is 15 characters (e.g., `22AAAAA0000A1Z5`), PAN is 10 (e.g., `AAAAA0000A`).
- **GST menu missing** — the store has no GSTIN saved; add it in Settings → Store.

## OTP & session errors

- **"Invalid OTP" / "Verification code has expired"** — codes last ~10 minutes; use resend (60-second cooldown).
- **"Too many failed attempts…"** — temporary lock; wait and retry or use Forgot Password.
- **"Session expired or access token revoked. Please login again."** — normal after a password change; sign in again.

## Errors — other frequent messages

- **"Store required" / store missing** — select a store from the header switcher first.
- **"Too many requests, please try again later."** — rate limit on public pages; wait a minute.
- **"Version conflict"** — the record changed on another device; refresh or resolve via the desktop sync prompt.
- **"You're offline / Check your connection"** — network dropped; the web app needs internet.

## FAQ

**Q: Feature button par crown/lock kyun dikh raha hai?** 
That module isn't in your plan — the crown marks plan-gated features; upgrading unlocks them.

**Q: Limit kab reset hoti hai?** 
Daily quotas reset each day, monthly each month; total counts (products, staff, stores) only free up when you delete items.

**Q: Staff ko error aa raha hai par owner ko nahi?** 
That's a permission gap, not a bug — the owner bypasses module permissions; grant the staff member the missing action.
