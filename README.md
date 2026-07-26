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
  frontmatter metadata + deterministic IDs; `app/rag/embedding_service.py` batched
  OpenAI `/embeddings`)
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
- **Output guard** (`app/guards/output_guard.py`): last check before the
  response leaves — secret/token/credential scrub and "currency amounts must
  come from tool results" validation. Modes via `AI_OUTPUT_GUARD_MODE`: `off`,
  `log` (default — flags only), `enforce` (secrets redacted in place;
  unverified numbers replaced by the safe fallback in
  `app/prompts/fallback.py`)
- **Authenticated** `POST /api/v1/chat` with LLM text, validated `toolCalls`, and
  **auto-executed READ** `toolResults` via retailer HTTP (forwarded user JWT)
- Tool-call JSON Schema validation with one repair retry
- Docker runtime and unit tests

Not implemented yet:

- Claude / Gemini / DeepSeek adapters
- Write / sensitive tools (idempotency + confirmation)
- Second LLM turn to ground `message` in `toolResults`
- `/voice`, `/image`, or `/document` APIs
- Conversation persistence, Redis rate limiting, queues, STT, TTS

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
| `AI_RAG_CONTEXT_MAX_TOKENS` | Token budget for the docs block in the prompt (default `2000`) |
| `AI_INPUT_GUARD_MODE` | `off` / `log` (default) / `enforce` |

Production requires HTTPS for JWKS and the OpenAI base URL. Never commit API keys.

## Chat API (Phase 3)

`POST /api/v1/chat` validates JWT + `storeId`, calls the active provider, validates
allowlisted tool calls, **executes READ tools** against retailer with the same
Bearer token and `?store=<storeId>`, and returns `toolCalls` + `toolResults`.

There is **no second LLM synthesis turn** yet — `message` is the first model reply.

| Tool | Retailer |
|---|---|
| `search_product` | `GET /product?store=&search=&limit=20` |
| `today_sale` | `GET /analytics/revenue?store=` → `data.today` |
| `stock_summary` | `GET /analytics/stock?store=` → `data.totals` |
| `payment_history` | `GET /customer-account/payments?store=&limit=20` |

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
  "message": "Main aaj ki sale nikaal sakta hoon.",
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
      "data": { "revenue": 0, "profit": 0, "sales": 0 }
    }
  ]
}
```

Error codes: `401` `AUTH_*` / `TOOL_UNAUTHORIZED`, `400` `STORE_ID_*` /
`TOOL_NOT_ALLOWED` / `TOOL_ARGS_INVALID`, `422` `VALIDATION_ERROR`,
`502` `AI_PROVIDER_ERROR`, `503` `AI_PROVIDER_NOT_CONFIGURED`.

Per-tool failures (`403`/`404`/`429`/5xx) return `toolResults[].success=false`
with `data.code` of `TOOL_FORBIDDEN` / `TOOL_NOT_FOUND` / `TOOL_RATE_LIMITED` /
`RETAILER_ERROR`.

## Local setup

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

## Tests and lint

```bash
source .venv/bin/activate
pytest
ruff check .
```

## Docker

```bash
docker compose up --build
```

Compose starts **Qdrant** (`localhost:6333`) and the AI service (`localhost:4004`).
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