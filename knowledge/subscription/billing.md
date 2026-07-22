---
module: subscription
feature: billing
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Buying a Plan & Billing History

## Overview

Plans are purchased from the **Pricing** page and paid online via **Razorpay** (UPI, cards, net banking). Only the store owner can buy or change a plan. After payment the subscription activates immediately across the account. Billing invoices and purchase history are available to the owner.

## Workflow

1. Open **Pricing** (from the Subscription page's upgrade button or `/pricing`).
2. Choose a plan and duration — 1, 3, 6, 12 months (longer terms carry discounts; 18/24/36/48 supported); apply a coupon code if you have one.
3. DragBizz creates a payment order (valid for **30 minutes**) and opens Razorpay checkout.
4. Complete payment; DragBizz verifies it and activates (or renews/changes) your subscription instantly.
5. **Billing history** — the owner can view past payments as invoices (amount, plan, cycle, status, paid date) and the subscription purchase history (plan name, dates, auto-renew).

## Business rules

- **Owner only** — staff get "Access Denied: Only store owners can purchase or modify subscriptions." and billing details are owner-only too.
- Amounts are in INR; GST percentage applies per package; the minimum chargeable order is ₹1.
- You cannot buy the same package while it's still active — renewal opens near the expiry date.
- Khata Free is not "purchased" — it's the automatic default; no billing entry exists for it.
- Payment verification is signature-checked; an already-processed payment can't be verified twice.

## Examples

- "Basic plan 1 saal ke liye lena hai" → Pricing → Basic → 12 months → pay ₹4,790 + GST via Razorpay.
- "Pichhle payment ka invoice chahiye" → Subscription/billing history (owner login) → invoices list.
- "Payment ho gaya par plan active nahi hua" → wait a moment and refresh; if the money was debited but verification failed, contact support with the payment ID.

## Errors

- `Payment order not found` / order expired (30 min) — start the purchase again.
- `Invalid payment signature` / `Missing required payment verification data` — verification failed; retry or contact support.
- `Payment already processed with status: {status}` — the payment was handled; check your plan status.
- `You already have an active subscription for this package. Please wait until closer to expiry date to renew.`
- `Package not found or not available` — the plan was changed/retired; reload Pricing.
- `Session is outdated. Please refresh or log in again.` — re-login and retry.

## FAQ

**Q: Which payment methods work?** 
Anything Razorpay supports — UPI, credit/debit cards, net banking, wallets.

**Q: Can staff buy the plan for the owner?** 
No — plan purchase and billing are restricted to the store owner's login.

**Q: Does the plan activate immediately after payment?** 
Yes — activation happens automatically as soon as the payment verifies.
