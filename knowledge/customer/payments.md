---
module: customer
feature: payments
version: 1
language: en
updated_at: 2026-07-22
status: shipped
---

# Collecting Customer Payments & Ledger Export

## Overview

There are three ways to collect a customer's dues from the khata: record a received payment (**You Got**), show a **UPI QR** at the counter, or send a **payment link** they can pay online. You can also export the full party ledger as a statement. Collect actions appear on the customer page when there is an outstanding balance.

## Workflow

1. **Record a payment (cash/UPI/bank)** — Khata tab → Record transaction → amount → payment mode → **You Got**. The payment is automatically allocated to the customer's unpaid released invoices, oldest first, updating their paid/partial status.
2. **Show UPI QR** — customer page → Collect payment → **Show UPI QR**. A QR for your store's default UPI ID appears with the due amount and note "Pay {customer name}". Configure UPI under Integrations → Payment.
3. **Payment link** — Collect payment → **Payment link**. DragBizz creates a Razorpay link for the due amount (or a custom amount) and copies the URL — share it on any channel. The customer pays on the hosted page; the khata updates when payment completes.
4. **Export statement** — Khata tab → **Download statement**; pick an optional date range (max 1 year); download as CSV or Excel. The statement shows opening balance, dated entries with You Gave (debit) / You Got (credit) columns, running balance, and closing balance.

## Business rules

- Collect buttons are enabled only when the customer has due > 0.
- Payment methods for recorded payments: Cash, UPI, Bank transfer (also Cheque/Credit via API).
- Payment links require the **customer payment gateway** feature — not included in the free Khata plan.
- Payment links expire in **7 days**; one active ledger link per customer. Requesting a link with a different amount cancels the old link and creates a new one.
- Paying via QR does not auto-record the payment — record a You Got entry when the money arrives. Gateway payment links do update automatically on success.
- Payments with invoice allocations cannot be deleted; delete is only possible for unallocated payments.
- Duplicate protection: retried submissions with the same idempotency key return the original payment instead of double-recording.

## Examples

- "Collect ₹350 cash from Ramesh" → Record transaction → 350 → Cash → You Got.
- "Send Ramesh a link to pay his ₹1200 due" → Collect payment → Payment link → link copied → share.
- "Give me Ramesh's statement for last month" → Download statement → set the date range → Excel.

## Errors

- `Payment reminders are not available in your current plan` style plan errors (`FEATURE_NOT_AVAILABLE`) — payment gateway/collect-link not in your plan.
- `INVALID_AMOUNT` — link amount must be greater than 0.
- No UPI configured — add a UPI ID in Integrations → Payment and set it as default.
- `Allocation amount exceeds due` / `Invoice must be RELEASED` — invoice allocation mismatch (usually from sync/API usage).
- `Cannot delete payment with invoice allocations` — the payment already settled invoices.
- Export date errors — end date must be after start date; range limited to 1 year.

## FAQ

**Q: The customer paid by QR — why does the khata still show due?** 
QR payments happen outside DragBizz. Record them with You Got. Only gateway payment links update automatically.

**Q: Can I collect more than the due as advance?** 
Yes — record a You Got entry for the full received amount; the extra becomes an advance (negative balance, shown green).

**Q: Which invoices does a payment settle first?** 
The oldest released invoices with dues, by release date (FIFO).

**Q: What format is the exported ledger?** 
CSV or Excel, generated on your device from the ledger data — includes opening/closing balance and per-entry running balance.
