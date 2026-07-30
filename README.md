# DragBizz AI Service

Provider-independent FastAPI foundation for DragBizz AI orchestration.

## Current scope

Implemented:

- FastAPI application factory and lifespan management
- Versioned health and readiness endpoints
- Request ID propagation (`X-Request-ID`)
- Structured JSON logging and consistent error responses
- **JWKS Bearer authentication** (Auth service contract)
- **OpenAI-compatible provider** + model router wiring from env
- **Qdrant vector DB** foundation (`VectorStore`, collection bootstrap, `/ready` status)
- **RAG chunking + embeddings** (`app/rag/chunker.py` markdown-aware chunks with
  frontmatter metadata + deterministic IDs; max ~450 tokens + ~80 overlap for
  tighter FAQ retrieval; `app/rag/embedding_service.py` batched OpenAI
  `/embeddings`)
- **RAG indexer** (`python -m app.rag.indexer`): incremental `knowledge/` → Qdrant sync
- **RAG retriever** (`app/rag/retriever.py`): question → top-k chunks with score
  threshold; Qdrant outage degrades to empty context (never fails chat)
- **RAG chat integration**: retrieved docs injected into the system prompt with
  source citations under a token budget; retrieval failure degrades to no docs;
  chat API contract unchanged
- **Input guard** (`app/guards/input_guard.py`): prompt-injection + off-topic
  heuristics before the LLM call. Modes via `AI_INPUT_GUARD_MODE`: `off`, `log`
  (default — flags only), `enforce` (returns a refusal in the same chat schema
  without spending tokens). Refusal copy: `app/prompts/refusal.py`
- **RAG vs tool routing**: system-prompt rules (live numbers → tools only;
  Documentation → how-to/features only) + "live/current" tool descriptions.
  Eval set: `tests/eval/routing_cases.json` (20 questions, also the seed for
  manual live-LLM routing evals)
- **Dynamic tool loading**: cue-based tool subsets on the first LLM call
  (`tool_selector.py`) — FAQ/docs/small-talk get no tool schemas; sale /
  stock / product / payment / customer / invoice get a family subset;
  unknown questions fail open to all registered tools
- **Intent-based prompt assembly**: `resolve_turn_intent` aligns with
  `routing_cases.json` (`tools`/`docs`/`both`/`neither`); system rules and
  RAG retrieval are gated by that label + the offered tool set
- **Compressed system prompt**: write / sensitive / grounding / invoice-chaining
  rules kept; formatting fluff and long examples removed
- **FAQ RAG budget**: docs/how-to/both use `AI_RAG_CONTEXT_MAX_TOKENS` (default
  `1000`); budget selected from routing via `rag_docs_budget_for_routing`
- **Output guard** (`app/guards/output_guard.py`): last check before the
  response leaves — secret/token/credential scrub and "currency amounts must
  come from tool results" validation. Modes via `AI_OUTPUT_GUARD_MODE`: `off`,
  `log` (default — flags only), `enforce` (secrets redacted in place;
  unverified numbers replaced by the safe fallback in
  `app/prompts/fallback.py`)
- **Authenticated** `POST /api/v1/chat` with LLM text, validated `toolCalls`, and
  **auto-executed READ + WRITE** `toolResults` via retailer HTTP (forwarded user JWT)
- **Write tools:** `create_customer`, `update_customer`, `create_invoice_draft`
  (draft only — no release), `ledger_credit` → retailer `PAYMENT`,
  `ledger_debit` → `DEBIT`. In-memory idempotency cache
  (`AI_IDEMPOTENCY_TTL_SECONDS`); ledger always sends `idempotencyKey`.
  AI-side audit log (no PII)
- **Second LLM synthesis turn** after tools: `message` is grounded in live
  `toolResults` (RAG docs stay in the system prompt); skipped when there were
  no tool calls; capped by `AI_CHAT_SYNTHESIS_MAX_TOKENS` (default `512`);
  synthesis output passes through `OutputGuard`
- **Session memory** keyed by `sessionId` + `userId` + `storeId`
  (sliding TTL, max turns + token budget); cross-user/store reuse → `403`
  `SESSION_FORBIDDEN`; prior turns (+ compact tool context) load into the next
  generation. Redis-backed when `AI_REDIS_URL` is set (else in-process)
- Tool-call JSON Schema validation with one repair retry
- **Admin model switch** (`GET`/`PUT /api/v1/admin/model`, platform admin
  only): runtime provider/model selection persisted in Redis
  (`AI_REDIS_URL`), applied per generation call without restart, model
  allowlist via `AI_OPENAI_ALLOWED_MODELS`
- **Per-tenant usage counters + hard caps**: daily token/cost counters per
  store (`GET /api/v1/admin/usage/{storeId}`); `AI_TENANT_DAILY_TOKEN_CAP`
  / `AI_TENANT_DAILY_COST_CAP_USD` return `429 AI_USAGE_CAP_EXCEEDED`
  before any LLM spend
- **Operational metrics** (`GET /api/v1/admin/metrics`): chat/provider
  latency, provider error count, per-tool success rate
- **Immutable tool-execution audit trail**: append-only JSONL at
  `AI_AUDIT_TRAIL_PATH` for every READ/WRITE/SENSITIVE execution (no PII)
- Docker runtime and unit tests

Details: [docs/features/ADMIN_AND_OBSERVABILITY.md](./docs/features/ADMIN_AND_OBSERVABILITY.md)
(includes the provider key rotation runbook).

Not implemented yet:

- Claude / Gemini / DeepSeek adapters
- `/voice`, `/image`, or `/document` APIs
- Rate limiting, durable Postgres history, queues, STT, TTS

The service does not access DragBizz databases directly. Tool handlers call
approved business-service APIs with caller identity and store scope preserved.

## Auth contract

Matches Auth / retailer access tokens:

| Setting | Value |
|---|---|
| Issuer | `DragBizz-auth` |
| Audience | `DRAGBIZZ` |
| Algorithm | `RS256` |
| Clock skew | 60s |
| JWKS | `{AI_AUTH_SERVICE_URL}/.well-known/jwks.json` |
| Transport | `Authorization: Bearer <access_token>` **or** HttpOnly cookie `at` / `__Host-at` (web) |

Claims used when present: `sub`, `agencyId`, `tenant`, `role`.

Protected routes require a valid access JWT (Bearer or session cookie).
`/api/v1/health` and `/api/v1/ready` remain public.

**Rate limiting:** deferred until Redis is available.

## Provider + retailer config

| Env | Purpose |
|---|---|
| `AI_ACTIVE_PROVIDER` | `openai_compatible` |
| `AI_OPENAI_API_KEY` | Required for chat when provider is active |
| `AI_OPENAI_BASE_URL` | Default `https://api.openai.com/v1` |
| `AI_OPENAI_MODEL` | e.g. `gpt-4o-mini` |
| `AI_CHAT_MAX_TOKENS` | Default `1024` |
| `AI_CHAT_SYNTHESIS_MAX_TOKENS` | Second-turn grounded answer cap (default `512`) |
| `AI_CHAT_TEMPERATURE` | Default `0.2` |
| `AI_PROVIDER_TIMEOUT_SECONDS` | Default `30` |
| `AI_RETAILER_SERVICE_URL` | Retailer base URL for tool HTTP |
| `AI_QDRANT_URL` | Qdrant HTTP URL (default `http://localhost:6333`) |
| `AI_QDRANT_API_KEY` | Optional Qdrant API key |
| `AI_QDRANT_COLLECTION` | Collection name (default `dragbizz_docs`) |
| `AI_EMBEDDING_MODEL` | Embedding model (default `text-embedding-3-small`) |
| `AI_EMBEDDING_DIMENSIONS` | Vector size for collection create (default `1536`) |
| `AI_RAG_TOP_K` | Max retrieved chunks per question (default `5`) |
| `AI_RAG_SCORE_THRESHOLD` | Min cosine score; lower-scoring chunks dropped (default `0.3`) |
| `AI_RAG_CONTEXT_MAX_TOKENS` | FAQ / how-to / both docs-block budget (default `1000`) |
| `AI_RAG_CONTEXT_MAX_TOKENS_ACTION` | Smaller docs budget for pure action/live turns (default `512`) |
| `AI_INPUT_GUARD_MODE` | `off` / `log` (default) / `enforce` — **must be `enforce` in production** |
| `AI_OUTPUT_GUARD_MODE` | `off` / `log` (default) / `enforce` — **must be `enforce` in production** |
| `AI_SESSION_TTL_SECONDS` | Sliding session TTL (default `1800`) |
| `AI_SESSION_MAX_TURNS` | Max stored user/assistant pairs (default `5`) |
| `AI_SESSION_HISTORY_MAX_TOKENS` | History token budget for LLM context (default `1200`) |
| `AI_IDEMPOTENCY_TTL_SECONDS` | Write-tool result cache TTL (default `86400`) |
| `AI_REDIS_URL` | Persists model selection, usage, sessions, idempotency, confirmations (empty = in-process) |
| `AI_OPENAI_ALLOWED_MODELS` | Extra models admins may activate (default model always allowed) |
| `AI_TENANT_DAILY_TOKEN_CAP` | Per-store daily token hard cap (`0` = disabled) |
| `AI_TENANT_DAILY_COST_CAP_USD` | Per-store daily cost hard cap (`0` = disabled) |
| `AI_AUDIT_TRAIL_PATH` | Append-only tool audit JSONL (default `data/tool_audit.jsonl`; empty disables) |

Production requires HTTPS for JWKS and the OpenAI base URL, and **both**
guard modes set to `enforce` (boot fails otherwise). Never commit API keys.

### Guard enforce rollout

1. Keep `log` in local/staging while watching false-positive warnings.
2. Tune `app/guards/*` if real store questions are blocked.
3. Set both modes to `enforce` before production traffic.

Details: [docs/features/GUARDS.md](./docs/features/GUARDS.md).

## Chat API (Phase 3.5)

`POST /api/v1/chat` validates JWT + `storeId`, calls the active provider, validates
allowlisted tool calls, **executes READ tools** against retailer with the same
Bearer token and `?store=<storeId>`, and returns `toolCalls` + `toolResults`.

When tools ran, a **second LLM synthesis turn** (no new tool calls) grounds
`message` in those results. With no tool calls, `message` is the first reply.

Prior turns for the same `sessionId` + user + store are loaded into the next
generation (in-memory TTL). Reusing another user's or store's `sessionId`
returns `403` `SESSION_FORBIDDEN`.

| Tool | Retailer |
|---|---|
| `search_product` | `GET /product?store=&search=&limit=20` |
| `today_sale` | `GET /analytics/revenue?store=` → `data.today` |
| `stock_summary` | `GET /analytics/stock?store=` → `data.totals` |
| `payment_history` | `GET /customer-account/payments?store=&limit=20` |
| `create_customer` | `POST /customer` |
| `update_customer` | `PUT /customer/:id` |
| `create_invoice_draft` | `POST /invoices` (always DRAFT; never release) |
| `ledger_credit` | `POST /customer-account/transactions` `type=PAYMENT` |
| `ledger_debit` | `POST /customer-account/transactions` `type=DEBIT` |

```bash
curl -sS -X POST "http://localhost:4004/api/v1/chat" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: demo-req-1" \
  -d '{
    "text": "Aaj ki sale kitni hai?",
    "sessionId": "session-abc",
    "storeId": "507f1f77bcf86cd799439011",
    "language": "hi-IN"
  }'
```

Example `200` body:

```json
{
  "message": "Aaj ki sale ₹500 hai.",
  "sessionId": "session-abc",
  "requestId": "demo-req-1",
  "userId": "<jwt-sub>",
  "provider": "openai_compatible",
  "model": "gpt-4o-mini",
  "toolCalls": [
    {
      "id": "call_abc",
      "name": "today_sale",
      "arguments": { "storeId": "507f1f77bcf86cd799439011" }
    }
  ],
  "toolResults": [
    {
      "tool": "today_sale",
      "success": true,
      "data": { "revenue": 500, "profit": 100, "sales": 3 }
    }
  ]
}
```

Error codes: `401` `AUTH_*` / `TOOL_UNAUTHORIZED`, `403` `SESSION_FORBIDDEN`,
`400` `STORE_ID_*` / `TOOL_NOT_ALLOWED` / `TOOL_ARGS_INVALID`,
`422` `VALIDATION_ERROR`, `429` `AI_USAGE_CAP_EXCEEDED`,
`502` `AI_PROVIDER_ERROR`, `503` `AI_PROVIDER_NOT_CONFIGURED`.

Per-tool failures (`403`/`404`/`409`/`429`/5xx) return `toolResults[].success=false`
with `data.code` of `TOOL_FORBIDDEN` / `TOOL_NOT_FOUND` / `TOOL_CONFLICT` /
`TOOL_RATE_LIMITED` / `RETAILER_ERROR`.

## Local setup

Dependencies are declared only in [`pyproject.toml`](./pyproject.toml).
`./setup.sh` creates `.venv` and runs `pip install -e ".[dev]"`.

```bash
./setup.sh
./run.sh                 # Docker Compose (qdrant + AI)
./run.sh --index         # Docker up, then index knowledge/
./run.sh --normal        # local .venv + uvicorn --reload
./run.sh --normal --index
```

Service endpoints:

- API: `http://localhost:4004`
- Swagger: `http://localhost:4004/docs`
- Health: `http://localhost:4004/api/v1/health`
- Readiness: `http://localhost:4004/api/v1/ready`
- Chat (auth required): `http://localhost:4004/api/v1/chat`
- Admin (platform admin token): `http://localhost:4004/api/v1/admin/model`,
  `/api/v1/admin/usage/{storeId}`, `/api/v1/admin/metrics`

## Tests and lint

```bash
source .venv/bin/activate
pytest                   # unit + api + eval
pytest tests/api/        # HTTP contracts (chat / health / auth / admin)
pytest tests/unit/       # module-level unit tests
ruff check .
```

Layout: `tests/api/` for FastAPI `TestClient` route contracts; `tests/unit/` for
pure module tests; `tests/eval/` for routing cases.

## Docker

```bash
docker compose up --build
```

Compose starts **Redis** (model selection, usage, sessions, idempotency, confirmations),
**Qdrant** (`localhost:6333`), and the AI service (`localhost:4004`).
The AI container gets `AI_QDRANT_URL=http://qdrant:6333`. For local (non-Docker) runs,
set `AI_QDRANT_URL=http://localhost:6333` and start Qdrant via compose:

```bash
docker compose up -d qdrant
```

On startup the service ensures collection `dragbizz_docs` (cosine, 1536 dims). If
Qdrant is down, chat still works — `/ready` reports `qdrant: unavailable` without
failing readiness until RAG retrieval is wired.

### Indexing knowledge docs

```bash
python -m app.rag.indexer            # index knowledge/ into AI_QDRANT_COLLECTION
python -m app.rag.indexer --root path/to/docs
```

Needs `AI_OPENAI_API_KEY` (embeddings) and a reachable Qdrant. Runs are
incremental and idempotent: deterministic chunk IDs mean unchanged docs are
skipped, changed docs re-embed only their changed chunks, and points for
removed docs are deleted. The summary logs files scanned, chunks
embedded/skipped, deletions, and estimated embedding cost. In production the
command requires an explicit `--yes`.

### Operations: monitoring, backup, reindex on deploy

**Per-request metrics.** Every completed chat request emits one structured
JSON log line (`"message": "Chat request metrics"`) with a `metrics` object:
`latency_ms`, `provider`/`model`, `input_tokens`/`output_tokens`,
`est_cost_usd` (priced via `AI_CHAT_INPUT_USD_PER_MILLION_TOKENS` /
`AI_CHAT_OUTPUT_USD_PER_MILLION_TOKENS`, defaults for gpt-4o-mini),
`retrieved_docs` (chunk id + source + score), and `tools_called`. Question
and answer text, user data, and tool arguments are never logged.

**Indexer alerts.** `python -m app.rag.indexer` exits `0` with
`Index run completed in Ns` on success, and exits `1` logging
`Index run FAILED` with the traceback on any error — point cron/CI alerting
at the exit code or that log marker.

**Qdrant backup.** Data lives in the `qdrant_storage` named volume (survives
`docker compose down`; only `down -v` removes it). The collection is fully
rebuildable from `knowledge/` via the indexer, so the docs in git are the
source of truth. For a point-in-time backup without reindexing (avoids
embedding cost), use Qdrant's snapshot API:

```bash
curl -X POST "http://localhost:6333/collections/dragbizz_docs/snapshots"
curl "http://localhost:6333/collections/dragbizz_docs/snapshots"   # list
```

**Reindex on deploy.** Whenever a deploy changes `knowledge/` docs (or the
chunker/embedding model), run the indexer after the new containers are up:

```bash
docker compose up -d --build
docker compose exec dragbizz-ai python -m app.rag.indexer --yes   # --yes needed in production
```

Runs are incremental — unchanged docs are skipped, so a no-docs-change deploy
costs nothing. A failed reindex leaves the previous points serving (chunks are
only deleted after their replacements are upserted), and chat degrades to
no-context rather than failing, so reindex failures are non-fatal but should
be alerted on and retried.

Docker exposes the service on `http://localhost:4004`. Downstream calls go through
nginx (`http://dragbizz.local`) — e.g. `AI_AUTH_SERVICE_URL=http://dragbizz.local/auth`
and `AI_RETAILER_SERVICE_URL=http://dragbizz.local/retailer`. The compose file maps
`dragbizz.local` to the host gateway.

## Configuration

Copy `.env.example` to `.env`. All service settings use the `AI_` prefix.

## Extension flow
1. Add more `ModelProvider` adapters in `app/providers/`.
2. Register and activate through `ModelRouter` / `AI_ACTIVE_PROVIDER`.
3. Add write/sensitive tool handlers with idempotency and confirmation.
4. Require validation, permissions, and confirmation according to each tool's risk.

## Full Co-Partner build docs

All future AI features are implemented **in this repo**, using product context from
`dragbizz-ai-service` but this codebase’s orchestration flow.

Start here: **[docs/README.md](./docs/README.md)**  
Hinglish quick guide: **[docs/QUICKSTART_HINGLISH.md](./docs/QUICKSTART_HINGLISH.md)**  
Master plan: **[docs/03_MASTER_IMPLEMENTATION_PLAN.md](./docs/03_MASTER_IMPLEMENTATION_PLAN.md)**