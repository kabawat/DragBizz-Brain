---
module: invoice
feature: payments
version: 1
language: en
updated_at: 2026-07-22
status: shipped
---

# Invoice Payments & Payment Links

## Overview

Every invoice tracks a payment status: `UNPAID`, `PARTIAL`, `PAID`, or `CANCELLED`. Payments can be collected at release time (Collect Payment modal), updated later on released invoices, allocated automatically from khata payments, or collected remotely via a payment link.

## Workflow

1. **Collect at release** — after creating an invoice (or POS checkout), the Collect Payment modal offers Cash, UPI (QR from your store's default UPI), Card, and Online (if a Razorpay gateway is configured). Confirm to release as paid, or choose "Release as unpaid instead".
2. **Update later** — on a `RELEASED` invoice, use **Update Payment Status** to set PAID, UNPAID, or PARTIAL with a paid amount and payment mode. Already-`PAID` invoices cannot be changed.
3. **Send payment link** — for a released invoice with due amount and a saved customer (not walk-in), use **Send payment link**. DragBizz creates a Razorpay payment link for the due amount; copy or share it. Links expire after **7 days** by default.
4. **Khata allocation** — recording a customer payment in khata automatically allocates it to that customer's released invoices with dues, oldest release first.
5. A cashbook entry is auto-created when a payment is recorded (best effort).

Supported payment modes: Cash, Credit Card, Debit Card, UPI, Cheque, Wallet, Online, Net Banking, Bank Transfer.

## Business rules

- Payment status can only be updated on `RELEASED` invoices.
- Marking PAID with a paid amount below the total applies a **settlement discount** (totals are recalculated).
- Marking PARTIAL with a paid amount at or above the total automatically becomes PAID.
- Payment links require the **customer payment gateway** feature on your plan, a `RELEASED` invoice, due amount above zero, and a customer attached to the invoice.
- If the payment was already recorded in the customer's khata ledger, the invoice payment update is blocked to avoid double counting.

## Examples

- "Mark invoice INV/25-26/0042 as paid by UPI" → Update Payment Status → PAID, mode UPI.
- "Customer paid ₹500 of a ₹800 bill" → PARTIAL with paid amount 500; due becomes ₹300.
- "Send a payment link for the pending amount" → invoice view → Send payment link → link copied; customer pays via the Razorpay page.

## Errors

- `INVOICE_NOT_RELEASED` — payment link requested on a draft.
- `INVOICE_NO_DUE` — payment link requested but nothing is due.
- `INVOICE_NO_CUSTOMER` — payment link needs a saved customer (walk-in not allowed).
- `Payment already recorded in khata ledger...` — the customer's khata already covers this payment.
- `No UPI configured` / `No default UPI` — set up UPI in Integrations → Payment (`/dashboard/integrations/payment`).
- Cannot change payment status of an already `PAID` invoice.

## FAQ

**Q: How long is a payment link valid?** 
7 days by default; after that its status becomes `EXPIRED` and a new link must be created.

**Q: Can a walk-in customer get a payment link?** 
No. Attach a saved customer to the invoice first.

**Q: Where does the customer pay?** 
On the Razorpay-hosted short URL. Payment success automatically updates the invoice.

**Q: Does a partial payment change the invoice status?** 
The invoice stays `RELEASED`; only its payment status becomes `PARTIAL` with the remaining due tracked.
