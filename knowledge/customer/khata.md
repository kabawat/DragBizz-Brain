---
module: customer
feature: khata
version: 1
language: en
updated_at: 2026-07-22
status: shipped
---

# Khata (Party Ledger)

## Overview

Every customer has a khata — a running ledger of what they owe (due) and what they have paid. Open it from the customer's page → **Khata** tab (`/dashboard/customers/[id]?tab=khata`), or via **Manage Khata** / **Quick entry** from the customer list. Entries are shown as **You Gave** (credit given — red, increases due) and **You Got** (payment received — green, reduces due), with a running balance after each entry.

## Workflow

1. **Open khata** — customer view → Khata tab. Quick stats show Balance (orange = due, green = advance), Total spent, Invoices, Items bought.
2. **Record an entry** — **Record transaction** button:
   - Enter Amount, pick payment mode (Cash / UPI / Bank transfer), optionally pick a note preset (Credit sale, Payment received, Advance, Opening balance, Settlement, Adjustment) or write notes.
   - Press **You Gave** to record credit given (udhari), or **You Got** to record a payment received. You Got payments are automatically allocated to the customer's unpaid released invoices, oldest first.
3. **Invoice entries appear automatically** — releasing an invoice for this customer adds an invoice debit; invoice payments add payment entries.
4. **Running balance** — each entry stores the balance after it; the ledger shows entries grouped by date with reference, payment mode, and notes.
5. **Delete an entry** — manual entries can be deleted (the balance is reversed). System entries from invoices/payments cannot be deleted directly — manage the related invoice or payment instead.
6. **Export** — see the payments & export doc (`Download statement` with optional date range, CSV/Excel).

## Business rules

- Entry types: manual **You Gave** (DEBIT), manual **You Got** (payment), opening balance, invoice debit, invoice payment, adjustment.
- You Gave / opening balance / invoice debit **increase** due; You Got / invoice payment **decrease** due (and increase total paid).
- Balance below zero means the customer has an **advance** with you.
- The khata account is created automatically with the customer (or on first entry); one account per customer with status Active/Inactive/Blocked.
- Amounts must be greater than 0.
- Khata payments do not create cashbook entries automatically (unlike invoice payments).
- Recording entries needs `customer` edit permission.

## Examples

- "Ramesh took goods worth ₹500 on credit" → Record transaction → 500 → **You Gave**.
- "Ramesh paid ₹200 cash" → Record transaction → 200 → Cash → **You Got** (auto-allocates to his oldest unpaid invoices).
- "How much does Ramesh owe?" → Khata tab balance card (orange = he owes you; green = advance).

## Errors

- `Enter a valid amount` — amount missing or ≤ 0.
- `System-generated transactions cannot be deleted directly. Use the related invoice or payment instead.` — tried to delete an invoice-linked entry.
- `This transaction belongs to a payment. Delete the payment instead.` — the entry is tied to a recorded payment.
- `Failed to load party ledger` — network/server issue; retry.

## FAQ

**Q: What is the difference between You Gave and You Got?** 
**You Gave** = you gave goods/money on credit (customer's due goes up). **You Got** = you received a payment (due goes down).

**Q: Do invoice sales show up in the khata automatically?** 
Yes. Releasing an invoice for a saved customer adds the amount to their khata; invoice payments reflect there too.

**Q: Can the balance be negative?** 
Yes — a negative balance means the customer paid in advance; the UI shows it in green as "Advance".

**Q: Can I edit a khata entry?** 
Entries cannot be edited. Delete a manual entry and re-add it, or use an adjustment.
