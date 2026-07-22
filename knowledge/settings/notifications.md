---
module: settings
feature: notifications
version: 1
language: en
updated_at: 2026-07-23
status: partial
---

# Notification Settings

## Overview

**Settings → Notifications** (`/dashboard/settings?tab=notifications`) has master toggles for four channels — **Email, SMS, WhatsApp, Push** — and per-category toggles (Account, Orders, Promotions, Billing, Security) under each. Enabling **Push** asks for browser notification permission and registers the device.

## What DragBizz actually sends today

- **Email** — login/reset OTPs, staff invitations, invoice created, order status updates, payment reminders, low-stock daily digest.
- **SMS** — OTPs only (login/reset, store-delete verification).
- **Push (browser)** — low-stock alerts on registered devices.
- **WhatsApp** — **not live yet**; the toggle exists but no WhatsApp messages are sent (roadmap).

## Workflow

1. Toggle a master channel on/off; category toggles under a disabled channel are greyed out.
2. Enabling **Push** triggers the browser permission prompt; if blocked, a help dialog explains how to re-allow notifications in browser settings.
3. **Reset to defaults** restores the standard configuration.

## Business rules

- Push works per device/browser — enable it on each device where you want alerts.
- Transactional OTPs (login, password reset, store delete) are always sent — they're security messages, not marketing.
- Category-level preferences are saved to your account, but fine-grained per-event filtering is still limited — treat the channel toggles (especially Push) as the reliable controls.
- Quiet hours / do-not-disturb are not available yet.

## Examples

- "Low stock alert on my laptop" → Notifications → enable Push → allow the browser prompt (see also inventory low-stock docs).
- "WhatsApp par reminder bhejna hai" → not available yet; reminders go by email today.

## Errors

- Push blocked — the help dialog walks through re-enabling notifications in the browser (site settings → Notifications → Allow).
- Push unsupported — some browsers/contexts (non-HTTPS) can't register for push.

## FAQ

**Q: Why did I get an OTP SMS with notifications off?** 
OTPs are security-critical and bypass preference toggles.

**Q: I enabled push but get nothing on my phone.** 
Push registration is per browser/device — open DragBizz on that device and enable push there. Low-stock alerts are the main push notification today.

**Q: When is WhatsApp coming?** 
It's on the roadmap; today the toggle is a placeholder and no WhatsApp messages are sent.
