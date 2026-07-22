---
module: supplier
feature: public-purchase-order
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Sharing Purchase Orders with Suppliers (Public PO Link)

## Overview

Every purchase order has a shareable **view-only** public link so your supplier can see the order without logging in. Share it from the PO list's **Send** menu via WhatsApp or Copy Link. The supplier sees the order details — no login or OTP is required.

## Workflow

1. Purchase Orders → PO row → **Send** → **WhatsApp** (opens a chat with the link) or **Copy Link**.
2. The supplier opens `.../view/purchase-order/<public-id>` in any browser.
3. The page shows: your store details (name, address, phone, email, GSTIN), the supplier name, ordered items (name, barcode, quantity, notes), PO status and approval status, dates, and notes.

## Business rules

- The link uses a random public ID — internal database IDs are never exposed.
- The link is **view-only**: the supplier cannot approve, reject, or edit the PO from it. Approval status changes happen inside DragBizz.
- No login, OTP, or expiry on the view link; anyone with the link can see the PO.
- Email and in-app Message sending are not available yet — use WhatsApp or copy the link manually.

## Examples

- "Send this order to Gupta Traders" → Send → WhatsApp → choose the supplier's chat.
- "Supplier says he can't see the order" → copy the link again and resend; any browser works, no app needed.

## Errors

- `Purchase order not found` — wrong or stale public ID (e.g., the PO was deleted).
- `ID is required` — malformed link.

## FAQ

**Q: Can the supplier confirm the order from the link?** 
No — the link is read-only. Record their confirmation yourself (the approval status is managed internally).

**Q: Does the link expire?** 
No built-in expiry. Deleting the PO makes the link stop working.

**Q: What if I edit the PO after sharing?** 
The same link always shows the current state of the PO — no need to reshare.
