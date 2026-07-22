---
module: sales-order
feature: ordering
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Placing & Tracking Online Orders (Customer Side)

## Overview

From the public catalog, customers check out in three steps: contact details → **5-digit OTP verification** → confirmation with an order number and a tracking link. In-store (table QR) orders skip the address and OTP. Customers can follow the order on a public tracking page.

## Workflow

1. **Cart → Secure Checkout.**
2. **Contact Information** — Full Name (required) plus phone (10 digits) and/or email; online orders also need a **Delivery Address** (street, city, state, pincode). In-store orders show the dining location instead — no address.
3. **Verify** — a 5-digit OTP goes to the phone/email; enter it and **Confirm Order**. In-store orders skip this step.
4. **Order Confirmed!** — shows the order number with **Track Order Status** and Continue Shopping.
5. **Tracking** — the public tracking page shows a status timeline: Pending → Confirmed → Processing → Shipped → In Transit → Out for Delivery → Delivered, with an activity history.

## Business rules

- At least one contact (phone or email) is required; name must be 2–100 characters.
- OTP session lasts **15 minutes**; resend has a 60-second cooldown; **5 wrong attempts** block the session (start over).
- Orders are created as **Pending / Unpaid** — the store confirms them; no payment is taken online at checkout.
- Customers **cannot cancel** an order from the tracking page — they contact the store.
- Order placement is rate-limited (10 requests/minute per visitor).

## Examples

- "Customer ne QR se order kiya" → order lands in your Sales Orders list as Pending (source Online or In-Store).
- "Customer poochh raha hai order kahan hai" → share the tracking link from the order confirmation.

## Errors

- "Please provide your name and contact details" — required fields missing.
- "Invalid OTP. X attempts remaining." / "Too many failed attempts. Session blocked."
- "Session expired or invalid. Please request a new OTP." — the 15-minute window passed.
- "Please wait Ns before resending OTP."
- "Order not found" — wrong/expired tracking link.

## FAQ

**Q: Customer ko OTP nahi mila?** 
Resend after the 60-second cooldown; check the phone number/email entered.

**Q: Can a customer change their order after placing it?** 
Not from the public page — the store can decline the pending order and the customer re-orders.

**Q: How does the customer pay?** 
At the counter/delivery, or the store sends a payment link. The tracking page reflects payment status once the store marks it paid.
