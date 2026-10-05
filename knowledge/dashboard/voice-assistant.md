---
module: dashboard
feature: voice-assistant
version: 1
language: en
updated_at: 2026-07-23
status: partial
---

# DragBizz Voice Assistant (Alt+V)

## Overview

The voice assistant is a floating pill available on every dashboard page. Press **Alt+V** (or click the pill) to open it, then **speak or type** a question. It answers store questions using live data — today's sales, stock totals, product search, and customer payment history. It works in English, Hindi, Hinglish, and Gujarati, following your app language.

## Workflow

1. Open with **Alt+V** or click the floating pill. **Esc** closes (or collapses full screen first).
2. Press the mic and speak — or type the question and press Enter.
3. Click the expand icon for a full-screen workspace (chat history | chat | live context).
4. Type `/` for slash shortcuts (sales, dues, stock, create-customer, invoice, and more). Arrow keys + Enter select a command.
5. The assistant replies with an answer; sensitive actions (invoice release) ask you to **Confirm** or **Cancel** first.
6. Use **New chat** / clear to reset the conversation.

## What it can answer today

- **Today's sale** — "Aaj ki sale kitni hai?" → today's revenue/sales from analytics.
- **Stock summary** — "Stock ka summary do" → stock totals (SKUs, quantities, low stock).
- **Product search** — "Sugar 1kg hai kya?" → product lookup by name.
- **Payment history** — "Recent customer payments dikhao" → latest customer payments.
- **Create customer** — "Can you create a new customer?" → yes; give name + phone or email and it creates the customer.
- **Draft invoice / khata writes** — create draft bills; **releasing** an invoice (stock deduct) always asks you to **Confirm** or **Cancel** in the chat panel first.

## Business rules

- **Invoice release** is never automatic from a single voice/text turn — Confirm in the app first. Cancel leaves the draft unchanged.
- Language follows the app setting: Hindi/Hinglish → Hindi speech recognition, Gujarati → Gujarati, otherwise Indian English.
- The microphone needs a secure context (HTTPS or localhost) and permission; without a mic you can still **type** questions.
- A store must be selected; answers are scoped to that store and to your own permissions (staff see only what their role allows).
- The mic runs only while listening (shown in the privacy note).

## Examples

- "Aaj kitne bill bane?" → today's sales count and amount.
- "Kya Parle-G stock mein hai?" → product search result with stock.
- "Is customer ne pichhla payment kab kiya?" → payment history lookup.
- `/create-customer` or `/invoice` → slash shortcuts fill a ready prompt.

## Errors

- "Open DragBizz over HTTPS or localhost to use the microphone" — insecure page; use the secure URL or type instead.
- "Microphone permission was denied" — allow mic access in browser settings.
- "Voice capture is not supported in this browser" — use Chrome/Edge, or type.
- "No microphone was found" / "Microphone used by another app".
- No store selected — pick a store first; the assistant shows a type-only notice.

## FAQ

**Q: How do I use DragBizz chat?**  
Open with Alt+V (or the chat button), type or speak your question, optionally expand to full screen, and use `/` for shortcuts. Pick a store first.

**Q: Can I create a customer by voice/chat?**  
Yes — give the customer name and a 10-digit phone or email. The assistant creates them for the active store.

**Q: Can I create an invoice by voice?**  
Yes for **draft** invoices (name the customer/products). **Releasing** a draft always needs Confirm in the chat panel first.

**Q: Which languages can I speak?**  
Hindi, Hinglish, Gujarati, and English — matching your app language setting.

**Q: Does it work without a microphone?**  
Yes — type your question in the panel; the AI works the same way.

**Q: Is my voice recorded all the time?**  
No — the microphone is active only while the listening indicator is on.

