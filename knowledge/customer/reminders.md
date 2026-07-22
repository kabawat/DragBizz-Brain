---
module: customer
feature: reminders
version: 1
language: en
updated_at: 2026-07-22
status: shipped
---

# Payment Reminders

## Overview

Send a one-tap payment reminder **by email** to a customer with an outstanding khata balance. The reminder includes the customer's name, your store name, the due amount, and (when a payment gateway is configured) a payment link so they can pay online. The **Remind** button is on the customer page next to the collect actions.

## Workflow

1. Open the customer (Details or Khata tab) — the **Remind** button appears in the Collect payment section when there is a due balance.
2. Press **Remind**. DragBizz emails the customer a payment reminder; if a payment link can be created it is included automatically.
3. Success shows "Payment reminder sent by email".

## Business rules

- **Email only** today. SMS and WhatsApp reminders are not available yet — they are on the roadmap.
- The customer must have an email address saved; the button is disabled otherwise.
- The customer must have due balance greater than 0.
- **Cooldown:** one reminder per customer per 24 hours — a repeat attempt within the window is rejected.
- Requires the `payment_reminder` feature (included in the free Khata plan) and customer create permission for staff.
- If the payment-link creation fails (e.g., no gateway configured), the reminder still goes out without a link.
- Reminders are sent manually (one at a time); scheduled and bulk reminders are not available yet.

## Examples

- "Remind Ramesh about his ₹1200 due" → open Ramesh → Remind → email sent with amount and payment link.
- "Why is Remind greyed out?" → the customer has no email, you lack permission, your plan lacks the feature, or there is no due.

## Errors

- `Customer email is required...` — add an email to the customer profile first.
- `Reminder was sent recently...` — 24-hour cooldown active; try later.
- `Payment reminders are not available in your current plan` — plan lacks the `payment_reminder` feature.
- `You do not have permission...` — staff permission missing.
- `{SMS|WHATSAPP} reminders are not available yet` — only email is supported.
- `Failed to send payment reminder` — email delivery failed; retry.

## FAQ

**Q: Can I send reminders by WhatsApp or SMS?** 
Not yet. Only email reminders are live; SMS/WhatsApp channels are planned.

**Q: Can I remind many customers at once?** 
Not currently — reminders are one customer at a time from their page.

**Q: What does the customer receive?** 
An email with your store name, their due amount in ₹, and a pay-now link when a gateway is configured.

**Q: How often can I remind the same customer?** 
Once every 24 hours.
