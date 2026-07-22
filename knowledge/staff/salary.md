---
module: staff
feature: salary
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Staff Salary

## Overview

Record salary payments at **Management → Staff → Salary** tab. Each payment records the staff member, amount, pay period (month), and payment mode. The tab shows a summary (total paid, payment count, breakdown by mode) and a monthly history. **Cash** salary payments are automatically logged in the Cashbook as Cash Out.

## Workflow

1. Staff page → **Salary** tab → record payment.
2. Fill: staff member, **amount**, **pay period** (month), **payment mode** (Cash, UPI, Bank Transfer, Cheque), optional notes; save.
3. If the period has **no attendance records**, a confirmation banner asks you to confirm before paying.
4. If a payment already exists for an **overlapping period**, you must confirm the duplicate before saving.
5. Review totals and history per month; entries can be edited or deleted.

## Business rules

- Amount must be greater than 0.
- **Cash payments auto-link to the Cashbook** (Cash Out); deleting the salary entry or changing its mode away from cash reverses the cashbook entry. (The salary screen doesn't currently show a hint about this — it happens automatically.)
- Salary is owner-managed; staff cannot see or record salaries.
- Requires the staff feature (paid plans).

## Examples

- "July ki salary ₹12,000 cash mein di" → Salary → staff → 12000 → period July → Cash → save; a Cash Out appears in the cashbook.
- "Advance de diya tha, dobara period aa raha hai" → the overlapping-period confirmation appears; confirm if intentional.
- "Is saal total salary kharcha?" → month-by-month summary totals.

## Errors

- "No attendance records found for this period…" — confirm to proceed without attendance.
- "A salary payment already exists for an overlapping period…" — confirm the duplicate to proceed.
- "Salary payment not found" — the entry was deleted.

## FAQ

**Q: Why did a Cash Out appear in my cashbook after paying salary?** 
Cash salary payments auto-link to the cashbook to keep counter cash accurate. UPI/bank/cheque payments don't.

**Q: Can I pay a partial/advance salary?** 
Yes — record any amount for the period; use notes to mark it as advance. Overlapping periods just need a confirmation.

**Q: Do salaries show in expenses?** 
They are tracked in the Salary tab (and cashbook if cash), separate from the Expenses module.
