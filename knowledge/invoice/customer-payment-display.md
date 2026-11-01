---
module: invoice
feature: customer-payment-display
version: 1
language: en
updated_at: 2026-07-22
status: shipped
---

# Customer Payment Display Screen

## Overview

The Customer Payment Display (`/dashboard/customer-payment`) is a full-screen, customer-facing screen for a second monitor or tablet at the counter. It mirrors the staff's Collect Payment session in real time: showing the amount due, a UPI QR code, card/online payment prompts, and a thank-you screen after payment. When idle it rotates welcome/offer slides or configured ads.

## Workflow

1. Staff opens it via the **Display** button (on the invoice list, POS, or collect modal) — it opens in a new window with no sidebar/header, meant to face the customer.
2. During checkout, the display follows the staff's collect session:
   - **Cash** → "Pay at counter" with the amount.
   - **UPI** → QR code generated from the store's default UPI ID.
   - **Card** → card terminal prompt.
   - **Online** → Razorpay checkout for the customer.
3. After successful payment it shows a thank-you screen, then returns to idle after a few seconds.

## Business rules

- Requires the `invoice` **create** permission; users without it are redirected to the invoice list.
- The UPI QR uses the store's default UPI ID — configure it under Integrations → Payment (`/dashboard/integrations/payment`).
- Idle content is the built-in welcome/offers rotation or store-configured ads.
- The display syncs automatically when the staff changes payment method or amount.

## Examples

- "Show the customer a QR to pay ₹350" → open Display, choose UPI in the collect modal; the QR appears on the customer screen.
- "Set up a customer-facing screen at my counter" → open `/dashboard/customer-payment` in a browser window on the second monitor and leave it running.

## Errors

- Redirected to invoices — you lack invoice create permission.
- "No UPI configured" / "No default UPI" — add a UPI ID in Integrations → Payment and mark it default.
- Online payment requires connectivity — offline mode shows a notice that online payment needs internet.

## FAQ

**Q: Does the display need its own login?** 
It runs in the same logged-in browser session; open it in a new window facing the customer.

**Q: Can I show my own promotions on the idle screen?** 
Yes — if ads/slides are configured for the store they replace the default welcome rotation.

**Q: Which payment methods appear?** 
Whatever the staff selects in the Collect Payment modal: cash, UPI QR, card, or online (Razorpay, if a gateway is configured).
