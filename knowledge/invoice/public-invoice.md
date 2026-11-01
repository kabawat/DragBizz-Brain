---
module: invoice
feature: public-invoice
version: 1
language: en
updated_at: 2026-07-22
status: shipped
---

# Sharing Invoices with Customers (Public Invoice Link)

## Overview

Every invoice has a shareable public link that customers can open without logging in. The link shows the invoice details (items, amounts, store and customer info) on a public page. This is separate from the payment link — the public invoice page is for viewing; payment links are for collecting dues.

## Workflow

1. Open the invoice → **Send** menu → **Copy link**, or use the WhatsApp share action (pre-filled message plus the link).
2. The customer opens `.../view/invoice/<public-id>` in any browser.
3. The page shows: invoice number, status, amounts, store details (name, address, phone, email, GSTIN), customer name/phone, and line items (name, quantity, price, GST rate, discount, total).

## Business rules

- The link uses a random public ID — internal database IDs are never exposed.
- No login or OTP is required to view; anyone with the link can see the invoice.
- The public endpoint is rate-limited (30 requests per minute per client) to prevent scraping.
- WhatsApp share sends a prepared message with the link (WhatsApp Business API automation is not live; this is a standard share).

## Examples

- "Send this bill to the customer on WhatsApp" → invoice view → Send → WhatsApp.
- "Customer wants to see the bill again" → copy the invoice link and send it; no app needed on their side.

## Errors

- `Invoice not found` — wrong or revoked public ID.
- Copy link not available — the invoice has no public ID; re-open or re-sync the invoice.
- Rate limit exceeded — too many requests from one device; wait a minute and retry.

## FAQ

**Q: Can the customer pay from the public invoice page?** 
No. To collect payment remotely, use **Send payment link** (a separate Razorpay link for the due amount).

**Q: Does the link expire?** 
The public invoice view link does not have a built-in expiry (unlike payment links, which expire in 7 days).

**Q: Is customer khata visible on the public page?** 
No. Only that single invoice's details are shown.
