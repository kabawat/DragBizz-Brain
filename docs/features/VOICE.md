# Feature: Voice & STT

## Goal

Speech → text (Indic-first), then reuse chat.

## APIs

- `POST /api/v1/voice/transcribe` multipart audio + `storeId` + optional `language`
- Optional query/body `runChat=true` → full `ChatResponse`

## Providers

- Primary: Sarvam (hi/gu)
- Fallback: Whisper / OpenAI audio

Interface under `app/integrations/stt/` with env `AI_STT_PRIMARY`.

## DoD

- Fixture audio returns stable transcript.
- Chat path unchanged when `runChat=true`.
- Failures return clear codes; no partial writes.
