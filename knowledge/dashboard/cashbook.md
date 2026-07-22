---
module: dashboard
feature: cashbook
version: 1
language: en
updated_at: 2026-07-23
status: partial
---

# Cashbook

## Overview

The Cashbook (`/dashboard/cashbook`) tracks daily cash in and cash out. The screen focuses on **today**: quick entry (amount + optional note → Cash In or Cash Out), today's totals, and the running closing balance. Cash sales, cash expenses, and cash salary payments are linked into the cashbook automatically so your counter cash stays reconciled.

## Workflow

1. **Quick entry** — enter the Amount, an optional note, then press **Cash In** (money received; recorded under Sale) or **Cash Out** (money paid; recorded under Other).
2. **Today cards** — Cash In (green), Cash Out (red), and Closing Balance for today.
3. **Today's entries** — each entry shows its note, time, and signed amount.
4. **Automatic entries** — created behind the scenes:
   - Releasing an invoice paid in **cash** → Cash In (Sale).
   - A **cash** expense marked **Paid** → Cash Out (Expense). The expense form shows a hint when this will happen.
   - A **cash** staff salary payment → Cash Out.
   - These auto-entries reverse automatically if the source is cancelled/deleted or its payment mode changes away from cash.

## Business rules

- Amount must be greater than 0 (large-amount cap applies).
- Days follow the Indian calendar day (IST); the closing balance carries into the next day's opening.
- One auto-entry per source document — no duplicates from the same invoice/expense/salary.
- Only cash-mode transactions auto-link; UPI/card/bank payments do not touch the cashbook.
- The current app screen is today-only: past-day browsing, date filters, editing/deleting entries, and manually setting a day's opening balance are **not available in the UI yet** (the backend supports opening-balance adjustments and history).
- Requires the `cashbook` feature (included in the free Khata plan) and cashbook staff permissions.

## Examples

- "Owner took ₹2000 from the counter" → Quick entry → 2000 → note "owner drawing" → Cash Out.
- "Why did a Cash In appear automatically?" → a cash invoice was released; it links to the cashbook by itself.
- "Aaj ka closing balance kya hai?" → the Closing Balance card on the cashbook (or the dashboard's Cashbook Today card).

## Errors

- "Enter a valid amount" — amount missing or ≤ 0.
- "Store required" — select a store first.
- "Failed to save entry" — retry; check connectivity.

## FAQ

**Q: Do UPI or card sales show in the cashbook?** 
No — only cash-mode transactions. The cashbook mirrors physical cash at the counter.

**Q: Can I edit yesterday's entries or set an opening balance?** 
Not from the current screen — it shows today only. Opening-balance adjustment exists in the backend and is coming to the UI.

**Q: What happens if I cancel a cash invoice?** 
Its automatic Cash In entry is reversed automatically.
