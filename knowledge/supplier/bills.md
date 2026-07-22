---
module: supplier
feature: bills
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Supplier Bills (Purchase Invoices)

## Overview

Supplier bills record what you purchased: create them directly at `/dashboard/bills/create` or from a purchase order (**Create Bill** on the PO). A bill lists items with quantities and purchase prices, computes GST automatically, tracks payment status (Paid / Partial / Pending / Overdue), and can **stock in the goods** — creating inventory batches — in the same step. Bills require a plan with the `billing` feature.

## Workflow

1. **Create a bill** — Bills → **Create Bill** (or from a PO row). Sidebar: Select Supplier (required), Purchase Order (optional — links the bill and pre-fills items), Payment Due Date (defaults to 30 days from today), Notes, and the **Stock In Goods?** checkbox.
2. **Add items** — product, quantity (> 0), purchase price per unit. At least one item; totals and GST are calculated server-side from your and the supplier's state (CGST/SGST vs IGST, ITC noted).
3. **Stock In Goods** — when checked, saving the bill creates stock batches for each item (linked to the bill and supplier). If the bill is linked to a PO, received quantities on the PO update automatically.
4. **Pay a bill** — from the bill row → **Pay Bill**, or Payments → Create Payment with type Bill Payment. Any unapplied advance payments to that supplier are applied to new bills automatically.
5. **View / Edit / Delete** — the bill page shows items, GST summary, linked batches, and outstanding amount, with PDF download. Editing recalculates totals; deleting a stocked-in bill also removes its batches.

## Business rules

- Bill number is auto-generated if not provided.
- Payment status: Unpaid → Partial → Paid; shown as **Overdue** when the due date passes with an amount still due.
- Up to 1000 items per bill; the supplier and all products must exist in your store.
- The bill's due date cannot be set in the past (app rule).
- Advance payments made to the supplier (including PO advances) are auto-applied when a matching bill is created.
- Staff need `supplier` permissions for bills; creating bills is gated by the `billing` plan feature.

## Examples

- "Record a purchase of 100 units of Sugar at ₹42 from Gupta Traders with stock in" → Create Bill → supplier + item + price → tick Stock In Goods → save.
- "Bill the goods received against PO-123" → PO row → Create Bill (items pre-filled, goods received checked).
- "Which bills are overdue?" → Bills list → status Overdue badges.

## Errors

- `Supplier is required` / `At least one item is required` / `Invalid quantity` — form validation.
- `Purchase order not found` — the selected PO doesn't belong to this store/supplier.
- `Some products not found` — an item references a product not in this store.
- Plan errors on create — the `billing` feature is not in your plan or quota is reached.

## FAQ

**Q: Does creating a bill add stock automatically?** 
Only when **Stock In Goods** is checked — then batches are created per item with the bill's purchase prices.

**Q: What's the difference between a bill and a purchase order?** 
A PO is your intent to buy (sent to the supplier); the bill records the actual purchase and payment obligation. A bill can be created from a PO or directly.

**Q: What happens to stock if I delete a stocked-in bill?** 
The batches created by that bill are removed and account balances are adjusted.

**Q: How is GST on purchases handled?** 
Calculated from item GST rates and states (CGST/SGST or IGST) with input tax credit (ITC) shown in the bill summary.
