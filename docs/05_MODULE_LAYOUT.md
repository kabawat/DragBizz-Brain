# 05 — Target Module Layout

Grow from the **current** tree. Do not delete working modules.

## Package policy (hygiene)

Decide before creating any new top-level `app/` folder:

1. **Create on need** — add a package in the phase that first needs a second file or a swappable backend. Do not pre-create empty Phase F/D folders.
2. **Store family stays packages** — `sessions/`, `idempotency/`, `confirmations/`, `usage/` are intentional one-implementation packages: Protocol (or clear store API) + InMemory now, Redis/Postgres later. Same pattern; do not flatten into callers.
3. **Executor boundary stays** — `executors/` is the tool runtime / risk policy layer (READ/WRITE/SENSITIVE). It is not a stub; keep it separate from `tools/` (definitions + handlers).
4. **Cluster Phase 5+ domains** — prefer the grouped tree below over seven more flat siblings (`analytics/`, `forecasting/`, `alerts/`, `events/`, `workers/`, …).
5. **API stays flat** — `api/v1/<route>.py` may name a product surface without forcing a matching empty `app/<feature>/` package.

### Thin packages reviewed (keep)

| Package | Why a package | Expected growth |
|---------|---------------|-----------------|
| `sessions/` | Chat history Protocol; multiple orchestrator consumers | Redis short cache (B1), Postgres durable history (B2) |
| `idempotency/` | AI-only write cache; injected beside other stores | Redis backend (reliability debt / B1) |
| `executors/` | Documented ToolExecutor boundary (policy + retailer dispatch) | Policy/audit splits inside the package if needed — not a second domain |
| `confirmations/` | Pending sensitive-action store (same family as sessions) | Redis |
| `usage/` | Tenant caps Protocol | Already has Redis store path |

### Phase 5+ grouping (decided)

Do **not** land `analytics/`, `forecasting/`, `alerts/`, `events/`, `workers/` as unrelated flat siblings. Use:

| Cluster | Path | When to create | Contains |
|---------|------|----------------|----------|
| Intelligence | `app/intelligence/` | First of F1 / F4 / F5 | `analytics/`, `forecasting/`, `alerts/` (pure functions + domain helpers; HTTP still under `api/v1/`) |
| Async runtime | `app/runtime/` | First of F2 / F3 | `workers/`, `events/` (Redis broker tasks + RabbitMQ consumer) |
| Imports | `app/imports/` | D2 | Vision catalogue pipeline (job lifecycle ≠ tools) |
| Persistence | `app/db/` | B2 | Alembic models / shared Postgres access only |
| Voice / STT | `app/integrations/stt/` | Voice phase | No top-level `app/voice/` — route only at `api/v1/voice.py` |

Import style example once intelligence lands:

```text
from app.intelligence.analytics.pareto import …
from app.runtime.workers.forecast_batch import …
```

Until a cluster has its first real module, **do not** create the parent folder.

---

## Target tree

```text
dragbizz-ai/
├── app/
│   ├── api/v1/
│   │   ├── router.py          # mount new routers
│   │   ├── health.py          # exists
│   │   ├── chat.py            # exists
│   │   ├── admin.py           # exists
│   │   ├── voice.py           # NEW (route only)
│   │   ├── imports.py         # NEW with D2
│   │   ├── insights.py        # NEW with F1
│   │   ├── dashboard.py       # NEW with F1
│   │   ├── forecast.py        # NEW with F4
│   │   ├── alerts.py          # NEW with F5
│   │   └── webhooks.py        # NEW with events/WhatsApp
│   ├── orchestrator/
│   │   ├── chat_service.py    # thin coordinator: handle / confirm
│   │   ├── chat_context.py    # session history + RAG + message assembly
│   │   ├── rag_budget.py      # action vs how-to docs token budget
│   │   ├── tool_loop.py       # bounded multi-round tool loop
│   │   ├── confirm_flow.py    # approve / reject confirmation path
│   │   ├── confirmation.py    # stage pending invoice confirmations
│   │   ├── ai_gateway.py      # LLM entry + chat/repair/synthesis turns
│   │   ├── model_router.py
│   │   ├── model_config.py
│   │   └── tool_call_validator.py
│   ├── sessions/              # keep — Protocol + InMemory / Redis
│   ├── idempotency/           # keep — AI write cache (InMemory / Redis)
│   ├── confirmations/         # keep — pending sensitive actions (InMemory / Redis)
│   ├── usage/                 # keep — tenant caps (InMemory / Redis)
│   ├── observability/         # metrics + audit trail
│   ├── tools/
│   │   ├── definitions.py     # READ + WRITE + SENSITIVE
│   │   ├── registry.py
│   │   ├── context.py
│   │   └── handlers/
│   │       ├── read_tools.py
│   │       ├── write_tools.py
│   │       └── confirm_tools.py
│   ├── executors/
│   │   └── tool_executor.py   # keep — risk policy + execute_* 
│   ├── providers/             # openai_compatible + gemini + …
│   ├── guards/
│   ├── rag/
│   ├── integrations/
│   │   ├── auth_jwks.py
│   │   ├── retailer_client.py
│   │   ├── utility_client.py  # NEW
│   │   ├── redis_client.py    # NEW
│   │   └── stt/               # NEW (voice) — not app/voice/
│   ├── intelligence/          # NEW cluster — create on first F1/F4/F5 file
│   │   ├── analytics/         # pareto / slow movers
│   │   ├── forecasting/       # nightly / per-SKU
│   │   └── alerts/            # dedupe ledger + notify helpers
│   ├── runtime/               # NEW cluster — create on first F2/F3 file
│   │   ├── workers/           # Redis-broker async tasks
│   │   └── events/            # RabbitMQ domain-event consumer
│   ├── imports/               # NEW at D2 — vision catalogue pipeline
│   ├── db/                    # NEW at B2 — Postgres / Alembic only
│   ├── prompts/
│   ├── schemas/
│   ├── core/
│   ├── config.py
│   ├── main.py
│   └── lifespan.py
├── knowledge/                 # RAG source of truth
├── migrations/                # Alembic (when B2)
├── tests/
│   ├── unit/
│   ├── api/
│   └── eval/
├── docs/                      # this pack
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## Coding conventions (match existing)

- Settings via `AI_*` env + `app/config.py`
- Errors via `AppError` + stable `code`
- Tools: define in `definitions.py`, register handler, never call retailer from orchestrator directly
- Pydantic schemas in `app/schemas/`
- Async I/O only for network/DB
- New top-level packages must satisfy the **Package policy** above (no ad-hoc `app/<feature>/` siblings)
