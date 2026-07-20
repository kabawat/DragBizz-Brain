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
- **Authenticated** `POST /api/v1/chat` with real LLM text + validated `toolCalls`
- Allowlisted read-tool **definitions** (schemas only; not executed yet)
- Tool-call JSON Schema validation with one repair retry
- Docker runtime and unit tests

Not implemented yet:

- Claude / Gemini / DeepSeek adapters
- Tool **execution** against retailer HTTP (`toolResults`)
- `/voice`, `/image`, or `/document` APIs
- Conversation persistence, Redis rate limiting, queues, STT, TTS
- Write / sensitive tools

The service does not access DragBizz databases directly. Future tool handlers must
call approved business-service APIs with caller identity and store scope preserved.

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

## Provider config

| Env | Purpose |
|---|---|
| `AI_ACTIVE_PROVIDER` | `openai_compatible` |
| `AI_OPENAI_API_KEY` | Required for chat when provider is active |
| `AI_OPENAI_BASE_URL` | Default `https://api.openai.com/v1` |
| `AI_OPENAI_MODEL` | e.g. `gpt-4o-mini` |
| `AI_CHAT_MAX_TOKENS` | Default `1024` |
| `AI_CHAT_TEMPERATURE` | Default `0.2` |
| `AI_PROVIDER_TIMEOUT_SECONDS` | Default `30` |

Production requires HTTPS for JWKS and the OpenAI base URL. Never commit API keys.

## Chat API (Phase 2)

`POST /api/v1/chat` validates JWT + `storeId`, calls the active provider, validates
allowlisted tool calls, and returns assistant text. **Tools are not executed yet**
(Phase 3). Missing API key → `503 AI_PROVIDER_NOT_CONFIGURED`.

Allowlisted read tools (schemas only): `search_product`, `today_sale`,
`stock_summary`, `payment_history`.

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
  ]
}
```

Error codes: `401` `AUTH_*`, `400` `STORE_ID_*` / `TOOL_NOT_ALLOWED` /
`TOOL_ARGS_INVALID`, `422` `VALIDATION_ERROR`, `502` `AI_PROVIDER_ERROR`,
`503` `AI_PROVIDER_NOT_CONFIGURED`.

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

Docker exposes the service on `http://localhost:3000`. Use
`AI_AUTH_SERVICE_URL=http://host.docker.internal:4000` so JWKS is reachable
from the container.

## Configuration

Copy `.env.example` to `.env`. All service settings use the `AI_` prefix.

## Extension flow

1. Add more `ModelProvider` adapters in `app/providers/`.
2. Register and activate through `ModelRouter` / `AI_ACTIVE_PROVIDER`.
3. Phase 3: attach handlers on allowlisted tools and call retailer HTTP.
4. Require validation, permissions, idempotency, and confirmation according to
   each tool's risk.
