---
module: supplier
feature: purchase-orders
version: 1
language: en
updated_at: 2026-07-23
status: partial
---

# Purchase Orders

## Overview

Purchase orders (`/dashboard/purchase-orders`) let you plan and track goods you order from suppliers: line items with quantities, expected delivery date, optional advance payment, and an approval status (Pending / Approved / Rejected). Goods receipt is tracked per line (ordered / received / pending), and stock enters your inventory when you **create a bill** from the PO with Stock In Goods. POs require a plan with the `purchase_order` feature.

## Workflow

1. **Create** — Purchase Orders → **Create PO**. Fields: Supplier (required, with add-new), Payment Due In (COD to 90 days, default 30), Expected Delivery Date (default 30 days), Reference Number, Notes (max 500), optional billing/shipping addresses, optional **advance payment** (Cash/UPI/Bank Transfer/Cheque), and line items (product + quantity).
2. **Track** — the list shows PO number, supplier, dates, received/total items with a progress bar, advance paid, and approval status. POs past their expected date with pending items show **Overdue**.
3. **Share with the supplier** — the Send menu offers **WhatsApp** and **Copy Link** (a public view-only link to the PO). Email/Message options are visible but not functional yet.
4. **Approval** — each PO carries an approval status (Pending / Approved / Rejected). The current app shows this status but has no approve/reject buttons — approval changes come through the API/desktop integrations. Receiving goods through the receive API requires the PO to be Approved.
5. **Receive goods / bill it** — the practical flow: PO row → **Create Bill** (items pre-filled, goods received checked) → stock batches are created and the PO's received quantities update. Partial receipts are supported — bill only what arrived.
6. **Advance payment** — record an advance during PO creation (or later via Payments → Advance Payment); it is applied automatically to the bill created against that PO.
7. **Edit / Delete** — edit core fields anytime from the PO page; deleting schedules the PO's removal and unlinks its advance payments.

## Business rules

- Supplier and at least one product (quantity > 0) are required.
- PO statuses: Draft, Sent, Acknowledged, Partially Received, Fully Received, Cancelled, Deleted, Expired — new POs start as Draft with approval Pending.
- Received quantity can never exceed the ordered quantity per line.
- The "Save Draft" button currently behaves the same as Create (no separate draft state is stored).
- Advance amounts show on the PO and are auto-applied to its bill.
- Staff need `purchase_order` permissions; creation is gated by the plan's purchase-order feature/quota.

## Examples

- "Order 200 units of Sugar from Gupta Traders, deliver in 2 weeks, ₹5000 advance by UPI" → Create PO → supplier, item, expected date, advance → create.
- "Send the PO to my supplier on WhatsApp" → PO row → Send → WhatsApp.
- "Half the goods arrived" → PO row → Create Bill with only the received quantities → stock in; the PO shows partial receipt progress.

## Errors

- `Supplier is required` / `At least one product is required` — form validation.
- `PO must be approved before receiving goods` — receive attempted on a Pending/Rejected PO (API flow).
- `Received quantity exceeds ordered quantity...` — trying to receive more than ordered.
- `Purchase Order already approved/rejected` — duplicate approval action.
- `Cannot receive goods for deleted PO` / `PO already deleted`.
- Plan errors — purchase-order feature not in plan or quota reached.

## FAQ

**Q: How do I mark goods as received?** 
Create a bill from the PO with the received quantities and Stock In Goods checked — inventory batches are created and the PO's received counts update.

**Q: Can the supplier approve the PO from the shared link?** 
No. The shared link is **view-only**. Approval status changes are internal (API/desktop); the app currently displays the status without approve/reject buttons.

**Q: What does Overdue mean on a PO?** 
The expected delivery date has passed and some ordered quantity is still pending.

**Q: Can I cancel an advance after deleting a PO?** 
Deleting the PO unlinks its advance payments; the advance remains with the supplier and will apply to their next bill.
