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
| Transport | `Authorization: Bearer <access_token>` only (no cookies) |

Claims used when present: `sub`, `agencyId`, `tenant`, `role`.

Protected routes require a valid Bearer JWT. `/api/v1/health` and `/api/v1/ready`
remain public.

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
./run.sh
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