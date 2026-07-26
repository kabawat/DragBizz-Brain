# Feature: Input / Output Guards (enforce rollout)

## Goal

Block prompt injection / off-topic inputs and stop secret leaks or invented
currency amounts from leaving the chat API — especially in production.

## Modes

| Mode | Behavior |
|---|---|
| `off` | Skip evaluation |
| `log` (dev default) | Evaluate and warn; still call LLM / return original text |
| `enforce` | Input: refuse without LLM spend. Output: redact secrets in place; replace unsupported ₹ amounts with safe fallback |

Env:

- `AI_INPUT_GUARD_MODE`
- `AI_OUTPUT_GUARD_MODE`

## Rollout (required path)

1. **Local / staging:** keep both modes on `log`. Watch warning logs for
   false positives (`Input guard flagged` / `Output guard flagged`) —
   matched fragment only; never full question/answer text.
2. Tune patterns in `app/guards/*` if legitimate store questions are blocked.
3. **Production:** set both to `enforce`. Boot **fails** if either is not
   `enforce` when `AI_ENVIRONMENT=production` (same class of check as HTTPS
   JWKS / OpenAI base URL).

```bash
AI_ENVIRONMENT=production
AI_INPUT_GUARD_MODE=enforce
AI_OUTPUT_GUARD_MODE=enforce
```

## Enforce behavior (contract)

| Guard | Enforce outcome |
|---|---|
| Input | Same `ChatResponse` schema; `provider=input_guard`, empty `model`, refusal `message`, empty tools; no LLM call |
| Output `SECRET_LEAK` | Secret substrings replaced with `[REDACTED]`; rest of answer kept |
| Output `UNSUPPORTED_NUMBERS` | Full message replaced by `get_fallback_message(language)` |

## DoD

- Prod settings validation requires enforce for both guards
- Unit tests cover refusal schema, secret redaction, unsupported amounts
- README + this doc describe when to flip
