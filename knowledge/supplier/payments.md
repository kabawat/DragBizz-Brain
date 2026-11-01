---
module: supplier
feature: payments
version: 1
language: en
updated_at: 2026-07-23
status: partial
---

# Supplier Payments

## Overview

Record money paid to suppliers at `/dashboard/payments`: bill payments, advances, adjustments, and refunds, using one or more payment methods per payment (Cash, UPI, Bank Transfer, Cheque, Credit). Bill payments update the bill's paid/due amounts; advances are held against the supplier and applied automatically to future bills or a chosen purchase order.

## Workflow

1. **Create a payment** — Payments → **Create Payment**. Choose:
   - **Payment Type** (required): Bill Payment / Advance Payment / Adjustment / Refund.
   - **Supplier** (required, searchable).
   - **Bill** — required for Bill Payment; picking a bill pre-fills the due amount. (Opening from a bill's **Pay Bill** action pre-selects it.)
   - **Payment methods** — one or more rows of Amount + Method + Reference. Method-specific fields: Bank Transfer needs bank name/IFSC/account/holder; UPI needs UPI ID + transaction ID; Cheque needs number/date/bank/branch.
   - Notes (max 500).
2. **Track** — the payments list shows payment number, supplier, date, amount, type, method, and status; view/edit/delete from the row menu.
3. **Advances** — record an Advance Payment (optionally linked to a PO). It shows on the PO and is applied automatically when a matching bill is created.

## Business rules

- Payments are recorded as **completed** immediately — there is no approval queue in practice (the Pending Payments and Reports screens exist but are not fully functional yet).
- Each payment method row needs an amount greater than 0; the total must be greater than 0.
- Bill payments cap at the bill's total — paid amount never exceeds it.
- Deleting a bill cleans up its linked payments' references.
- Staff need `billing`/`supplier` permissions for payment screens.

## Examples

- "Pay Gupta Traders' bill of ₹4200 by bank transfer" → Create Payment → Bill Payment → supplier → bill → Bank Transfer details → save.
- "Give ₹5000 advance for the upcoming order" → Create Payment → Advance Payment → supplier (optionally link the PO).
- "Split a payment: ₹2000 cash + ₹3000 UPI" → add two method rows in one payment.

## Errors

- `bill is required for BILL_PAYMENT` — pick the bill being paid.
- `payment must be a non-empty array` / `Invalid payment amount` / `Total payment amount must be greater than 0`.
- Method-specific validation — missing UPI ID/transaction ID, bank details, or cheque details.
- `Supplier payment not found` — viewing a deleted payment.
- `Access denied...` — staff permission missing.

## FAQ

**Q: Where does an advance payment go if there's no bill yet?** 
It stays with the supplier and is applied automatically to their next bill (PO-linked advances prefer that PO's bill).

**Q: Can I record one payment across multiple bills?** 
No — a bill payment targets one bill. Make separate payments, or use an advance which auto-applies.

**Q: Why is the Pending Payments page empty?** 
Payments are recorded as completed immediately; an approval workflow is not live yet.

**Q: Is there a payment reports screen?** 
The Reports page exists but is still being built — use the supplier analytics dashboards for reliable numbers.
