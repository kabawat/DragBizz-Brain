---
module: settings
feature: payments
version: 1
language: en
updated_at: 2026-07-25
status: shipped
---


# UPI IDs & Payment Gateway Setup

## Overview

Payment collection settings live under **Integrations → Payment** (`/dashboard/integrations/payment`), with two sub-tabs: **UPI** (for counter QR codes) and **Payment Gateway** (Razorpay and similar, for online payment links). UPI powers the "Show UPI QR" collect flow and the customer payment display; the gateway powers payment links on invoices and khata.

This page is **only** for UPI + payment gateways. **Tally** (`/dashboard/integrations/tally`) is a separate accounting export — never point payment-gateway questions to Tally.

## Workflow

### UPI IDs

1. **Add UPI ID** — enter the UPI ID (format `username@bank`, e.g. `merchant@paytm`), an optional label, and assign it to one or more stores. Toggle **Set as default** if this should be the primary ID.
2. The list lets you view/download each UPI's QR, edit, set default, or delete (with confirmation).

### Payment gateway

1. **Add gateway** — choose the type (Razorpay, Paytm, Cashfree), mode (**Test** or **Live**), and assign stores.
2. For Razorpay enter your **Key ID** and **Key Secret** from the Razorpay dashboard.
3. DragBizz shows a **webhook URL and a DragBizz-generated webhook secret** — copy both into your Razorpay webhook settings. A regenerate button issues a fresh secret if needed.
4. The gateway starts **Unverified** and becomes **Verified** automatically once the first webhook from the provider is received successfully.

## Business rules

- UPI ID must match `username@bank`; duplicates within the account are rejected; up to 50 UPI IDs; **one default per account**.
- The first UPI ID you add becomes the default automatically.
- One gateway of each type per account; the webhook secret is managed by DragBizz (you can't type your own — use regenerate).
- Regenerating the webhook secret resets verification — update Razorpay with the new secret.
- Payment links require a configured, active gateway and the `customer_payment_gateway` plan feature.
- There is no "test connection" button — verification happens via the first real webhook.

## Examples

- "Custom / payment gateway integrate karna hai?" → Integrations → Payment → Payment Gateway → add Razorpay / Paytm / Cashfree (not Tally).
- "Counter par UPI QR chahiye" → add your UPI ID here, set default → the Collect Payment → Show UPI QR uses it.
- "Invoice payment links setup karne hain" → add Razorpay in Live mode with your Key ID/Secret, configure the webhook, wait for Verified.
- "Webhook secret leak ho gaya" → Regenerate secret → update it in the Razorpay dashboard.

## Errors

- "Invalid UPI ID format… Format: username@bank (e.g. merchant@paytm)".
- "UPI ID already exists for this agency".
- "At least one store ID is required" — assign the UPI/gateway to a store.
- "Payment gateway already exists for this agency" — edit the existing one instead.
- "Invalid payment gateway payload or credentials" — check the Key ID/Secret.
- "Webhook secret rotation is not supported for this gateway type".

## FAQ

**Q: Does DragBizz let me integrate a payment gateway / custom payment gateway?**  
Yes — under [Integrations → Payment](/dashboard/integrations/payment) → **Payment Gateway**. Supported types today: **Razorpay, Paytm, Cashfree** (Test or Live). There is no open "bring any custom SDK / arbitrary gateway" option beyond these types.

**Q: Where do I open payment gateway settings after setup?**  
Always [Integrations → Payment](/dashboard/integrations/payment) — not Tally, not GST. Tally is a separate accounting-export integration.

**Q: Do QR payments record automatically in DragBizz?** 
No — UPI QR payments happen outside the app; record them as You Got / invoice payment. Only gateway payment links update automatically.

**Q: Why does my gateway say Unverified?** 
No webhook has arrived yet. Make sure the webhook URL and secret are saved in your Razorpay dashboard, then run a test payment.

**Q: Can different stores use different UPI IDs?** 
Yes — each UPI ID is assigned to specific stores; the default is used when a store has no specific assignment.
