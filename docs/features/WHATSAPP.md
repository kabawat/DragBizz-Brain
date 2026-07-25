# Feature: WhatsApp Channel

## Goal

Meta Cloud API as first-class channel for text/voice → same tools as in-app chat.

## Build on this repo

| Piece | Module |
|---|---|
| Webhook | `app/api/v1/webhooks.py` |
| HMAC | `app/core/whatsapp_sig.py` |
| Phone ↔ store map | Postgres table |
| Media + STT | worker + STT client |
| Reply | `UtilityClient` |
| Brain | `ChatService` (shared) |

## Rules

- Fast webhook ACK; process async.
- Confirmation for invoice release (Flow 2/3).
- Language preserved in replies.
- Internal/secret auth for utility; never expose Meta tokens to clients.

## DoD

- Staging: Gujarati voice note → draft → confirm → released invoice message.
