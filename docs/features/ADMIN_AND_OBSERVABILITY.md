# Admin model switch, cost caps, observability (Phase 7)

Status: shipped July 2026.

## Authorization

All `/api/v1/admin/*` endpoints require a **platform admin** access token —
`role` claim `admin` or `super_admin`, issued by dragbizz-auth's Admin
login (`/admin/login-verify`). This mirrors the retailer service's
`admin.middleware.js` (which also excludes `manager`).

Store owners and staff get `403 ADMIN_FORBIDDEN`: the model selection is
**service-global**, so a store-level role must not be able to change the
model (and its cost) for every other tenant.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/admin/model` | Active provider/model, available providers, allowed models |
| `PUT` | `/api/v1/admin/model` | Switch active provider/model (no restart) |
| `GET` | `/api/v1/admin/usage/{storeId}` | Today's per-tenant token/cost counters + configured caps |
| `GET` | `/api/v1/admin/metrics` | Process metrics: chat/provider latency, provider errors, tool success rate |

### Switching the model

```bash
curl -X PUT "http://localhost:4004/api/v1/admin/model" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"provider": "openai_compatible", "model": "gpt-4o"}'
```

Validation:

- `provider` must be a registered provider (`400 ADMIN_PROVIDER_UNKNOWN`).
- `model` must be in the allowlist: `AI_OPENAI_MODEL` ∪
  `AI_OPENAI_ALLOWED_MODELS` (`400 ADMIN_MODEL_NOT_ALLOWED`). This stops a
  compromised admin token from activating an arbitrary expensive model.

The switch takes effect on the **next generation call** — the gateway reads
the selection per request. Every change is logged with an `audit` object
(`action=model_selection`, provider, model, `updatedBy`).

**Pricing caveat:** `AI_CHAT_INPUT_USD_PER_MILLION_TOKENS` /
`AI_CHAT_OUTPUT_USD_PER_MILLION_TOKENS` describe the *active* model. When
switching model families, update these envs too or cost counters/caps will
be computed with stale prices. Token caps are pricing-independent.

## Persistence

With `AI_REDIS_URL` set (docker-compose provides `redis://redis:6379/0`),
the selection is stored in Redis (`ai:model_selection`) and survives
restarts and multiple instances. Without Redis the store is in-process:
a restart falls back to the env defaults (`AI_ACTIVE_PROVIDER` /
`AI_OPENAI_MODEL`) — production boot logs a warning in that case.

Degradation policy (availability over strictness for chat):

- Selection **read** failure (Redis outage / corrupt value) → env defaults,
  chat keeps working.
- Selection **write** failure → the admin `PUT` fails loudly.

## Per-tenant usage counters and hard caps

Every chat request accumulates `requests`, `input_tokens`,
`output_tokens`, and estimated `cost_usd` per `storeId` per UTC day
(Redis hash `ai:usage:{storeId}:{YYYY-MM-DD}`, 48h TTL; in-process
fallback without Redis).

Hard caps (both default **0 = disabled**):

| Env | Meaning |
|---|---|
| `AI_TENANT_DAILY_TOKEN_CAP` | Max input+output tokens per store per UTC day |
| `AI_TENANT_DAILY_COST_CAP_USD` | Max estimated USD per store per UTC day |

When a store's existing usage has reached a cap, `POST /api/v1/chat`
returns `429 AI_USAGE_CAP_EXCEEDED` **before any LLM call**. Enforcement is
post-paid: the request that crosses the cap completes; the next one is
blocked. A Redis outage fails **open** (caps suspended, chat unaffected)
and is logged.

## Metrics

`GET /api/v1/admin/metrics` returns per-instance in-process counters:

```json
{
  "chat": {"requests": 42, "capBlocked": 1, "latency": {"avgMs": 812.4, "maxMs": 2101.0}},
  "provider": {"calls": 97, "errors": 2, "latency": {"avgMs": 640.1, "maxMs": 1900.2}},
  "tools": {
    "executions": 55, "failures": 3, "successRate": 0.9455,
    "byTool": {"today_sale": {"executions": 20, "failures": 0}}
  }
}
```

Counters reset on restart (like a Prometheus target before scrape).
Durable per-request detail stays in the structured
`"Chat request metrics"` log lines (latency, tokens, cost, retrieved docs,
tools called — never question/answer text).

## Immutable audit trail

Every executed tool call (READ, WRITE, and confirmed SENSITIVE) appends one
JSON line to `AI_AUDIT_TRAIL_PATH` (default `data/tool_audit.jsonl`,
volume-mounted in docker-compose; empty value disables):

```json
{"ts": "2026-07-30T10:00:00+00:00", "sessionId": "s1", "userId": "u1",
 "storeId": "…", "tool": "create_customer", "success": true,
 "errorCode": null, "idempotencyKeyPrefix": "…", "cacheHit": false}
```

- The service only ever opens the file in append mode and exposes **no**
  read/update/delete API — rotation/shipping/retention are ops concerns
  (logrotate `copytruncate` is safe: the writer re-appends).
- Events never contain tool arguments, phone numbers, amounts, or free
  text (PII rule). The same event is also logged (`"Tool execution audit"`).

## Ops runbook: rotating provider API keys

The OpenAI(-compatible) key lives **only** in the `AI_OPENAI_API_KEY` env
(never in git, never in Redis, never logged — the output guard also scrubs
`sk-…` patterns from responses).

1. **Create the new key** in the provider dashboard (keep the old one
   active — providers allow multiple concurrent keys).
2. **Verify the new key** without touching the service:

   ```bash
   curl -s https://api.openai.com/v1/models \
     -H "Authorization: Bearer $NEW_KEY" | head -c 200
   ```

3. **Update the secret**: edit `.env` (`AI_OPENAI_API_KEY=<new>`) or the
   deployment secret store.
4. **Restart the service** — the key is read at request time from settings
   loaded at boot:

   ```bash
   docker compose up -d dragbizz-ai
   ```

5. **Verify**: `GET /api/v1/ready` shows `ai_provider: ok`, then run one
   authenticated chat request and check a `"Chat request metrics"` log
   line appears without `AI_PROVIDER_ERROR`.
6. **Revoke the old key** in the provider dashboard only after step 5.
7. If chat breaks after rotation, re-set the old key and restart
   (rollback), then repeat from step 2.

The same procedure applies to `AI_QDRANT_API_KEY` (embeddings/RAG) —
verify with a Qdrant `GET /collections` call instead.

Rotate immediately (not on schedule) if a key appears in logs, a commit,
or an incident. `.env.bak`-style files must never be committed (see repo
hygiene TODO).
