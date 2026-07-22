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

1. Open with **Alt+V** or click the floating pill (drag it anywhere; position is remembered). **Esc** closes.
2. Press the mic and speak — the assistant listens, converts speech to text, and sends it — or type the question and press Enter.
3. The assistant replies with an answer; when it used store data it lists the lookups it ran with a done/failed marker.
4. Clear resets the conversation.

## What it can answer today (read-only)

- **Today's sale** — "Aaj ki sale kitni hai?" → today's revenue/sales from analytics.
- **Stock summary** — "Stock ka summary do" → stock totals (SKUs, quantities, low stock).
- **Product search** — "Sugar 1kg hai kya?" → product lookup by name.
- **Payment history** — "Recent customer payments dikhao" → latest customer payments.

## Business rules

- Voice queries are **read-only** today. Creating customers/invoices, recording khata entries, or any money/stock action by voice is **not available yet** (planned with a confirmation step).
- Language follows the app setting: Hindi/Hinglish → Hindi speech recognition, Gujarati → Gujarati, otherwise Indian English.
- The microphone needs a secure context (HTTPS or localhost) and permission; without a mic you can still **type** questions.
- A store must be selected; answers are scoped to that store and to your own permissions (staff see only what their role allows).
- The mic runs only while listening (shown in the privacy note).

## Examples

- "Aaj kitne bill bane?" → today's sales count and amount.
- "Kya Parle-G stock mein hai?" → product search result with stock.
- "Is customer ne pichhla payment kab kiya?" → payment history lookup.

## Errors

- "Open DragBizz over HTTPS or localhost to use the microphone" — insecure page; use the secure URL or type instead.
- "Microphone permission was denied" — allow mic access in browser settings.
- "Voice capture is not supported in this browser" — use Chrome/Edge, or type.
- "No microphone was found" / "Microphone used by another app".
- No store selected — pick a store first; the assistant shows a type-only notice.

## FAQ

**Q: Can I create an invoice by voice?** 
Not yet — voice actions are read-only. Write actions with a confirmation step are on the roadmap.

**Q: Which languages can I speak?** 
Hindi, Hinglish, Gujarati, and English — matching your app language setting.

**Q: Does it work without a microphone?** 
Yes — type your question in the panel; the AI works the same way.

**Q: Is my voice recorded all the time?** 
No — the microphone is active only while the listening indicator is on.
