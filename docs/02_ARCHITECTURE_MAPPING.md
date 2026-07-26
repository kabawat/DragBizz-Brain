# 02 — Architecture Mapping

How `dragbizz-ai-service` concepts map onto **this** codebase.

## High-level

```text
dragbizz-ai-service                    dragbizz-ai (implement here)
─────────────────────                  ────────────────────────────
LangGraph agent state machine    →     ChatService + explicit confirm state
                                       (app/sessions InMemorySessionStore;
                                        Redis later)
app/agents/tools/*               →     app/tools/definitions.py
                                       app/tools/handlers/*
                                       app/tools/registry.py
Tool executor                    →     app/executors/tool_executor.py
                                       (extend beyond READ)
LLM clients (openai/gemini)      →     app/providers/* + ModelRouter
RAG / LlamaIndex + pgvector      →     app/rag/* + Qdrant (keep)
clients/retailer (internal)      →     app/integrations/retailer_client.py
                                       (+ optional internal-secret mode)
clients/utility                  →     app/integrations/utility_client.py (new)
Celery workers                   →     app/workers/* + Redis broker (new when needed)
RabbitMQ consumers               →     app/events/* (new)
Postgres models                  →     app/db/* only when persistence required
api/rest/v1/*.py under /ai       →     app/api/v1/*.py under /api/v1
```

## Request path today (keep)

```text
Client
  → Nginx (/ai/* → :4004 optional)
  → FastAPI /api/v1/chat
  → deps: JWT + storeId
  → ChatService.handle
        → InputGuard
        → load session history (sessionId + userId + storeId)
        → Retriever (Qdrant) → docs block
        → AiGateway.generate (tools schema)
        → ToolCallValidator
        → ToolExecutor.execute_reads (RetailerClient + user JWT)
        → (if tools) synthesis turn: second LLM call with toolResults → grounded message
        → OutputGuard
        → append turn to session store
  → ChatResponse { message, toolCalls, toolResults }
```

## Target path (same spine)

```text
ChatService.handle (extended)
  → InputGuard
  → load session history (in-memory; Redis/Postgres later)
  → Retriever
  → AiGateway.generate
  → ToolCallValidator
  → ToolExecutor
        → READ  → auto execute (today)
        → WRITE → create draft via retailer; return confirmation payload
        → SENSITIVE → never auto; require explicit confirm API/turn
  → synthesis turn (done for READ): second LLM call with toolResults → grounded message
  → OutputGuard
  → persist turn to session store (+ durable store later)
```

## Auth modes

| Caller | Mode | Implementation |
|---|---|---|
| App / web user | JWKS JWT (current) | `app/integrations/auth_jwks.py`, `app/core/security.py` |
| Meta WhatsApp | HMAC signature | new `app/core/whatsapp_sig.py` |
| Node → AI internal | `X-Internal-Secret` + IP | new middleware (port from service / retailer) |
| AI → retailer (user tools) | Forward user JWT (current) | keep for READ/WRITE as retailer allows |
| AI → retailer (jobs/webhooks) | Internal secret | extend `RetailerClient` |
| AI → utility | Internal secret | `UtilityClient` |

## Data stores — when to add what

| Need | Store | Why |
|---|---|---|
| Help/docs RAG | **Qdrant** (existing) | Already wired; rebuildable from `knowledge/` |
| Short-lived chat session | **In-memory** (now) → **Redis** | Process-local until B1 |
| Chat history, jobs, alerts, forecasts, usage | **Postgres** | Relational + audit; add Alembic when durable history needed |
| Rate limit, idempotency, short session, broker | **Redis** | Matches DragBizz ops; unlocks workers |
| Domain events | **RabbitMQ** | Same bus as retailer when proactive features land |

Do **not** migrate RAG off Qdrant in early phases. Postgres `pgvector` is optional later for tenant business embeddings if product requires it.

## Risk model (already in code)

```python
class ToolRisk(StrEnum):
    READ = "read"           # auto-execute
    WRITE = "write"         # draft + confirm
    SENSITIVE = "sensitive" # confirm + extra policy
```

Extend `ToolExecutor`:

- `execute_reads` — keep
- `execute_writes` — propose drafts, never release unless confirm flag/tool
- `execute_confirmations` — release/approve endpoints with idempotency

## Naming

Prefer existing names: `ChatService`, `ToolRegistry`, `RetailerClient`, `AI_*` env prefix, `/api/v1`.  
Gateway can strip/rewrite `/ai` → this service without changing internal routes.
