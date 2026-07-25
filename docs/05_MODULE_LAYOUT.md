# 05 — Target Module Layout

Grow from the **current** tree. Do not delete working modules.

```text
dragbizz-ai/
├── app/
│   ├── api/v1/
│   │   ├── router.py          # mount new routers
│   │   ├── health.py          # exists
│   │   ├── chat.py            # exists → extend confirm
│   │   ├── voice.py           # NEW
│   │   ├── imports.py         # NEW
│   │   ├── insights.py        # NEW
│   │   ├── dashboard.py       # NEW
│   │   ├── forecast.py        # NEW
│   │   ├── alerts.py          # NEW
│   │   └── webhooks.py        # NEW
│   ├── orchestrator/
│   │   ├── chat_service.py    # extend: history, synthesis, confirm
│   │   ├── ai_gateway.py
│   │   ├── model_router.py
│   │   └── tool_call_validator.py
│   ├── tools/
│   │   ├── definitions.py     # READ + WRITE + SENSITIVE
│   │   ├── registry.py
│   │   ├── context.py
│   │   └── handlers/
│   │       ├── read_tools.py
│   │       ├── write_tools.py     # NEW
│   │       └── confirm_tools.py   # NEW (or chat confirm endpoint)
│   ├── executors/
│   │   └── tool_executor.py   # execute_reads + writes + policy
│   ├── providers/             # openai_compatible + gemini + …
│   ├── guards/                # keep
│   ├── rag/                   # keep Qdrant pipeline
│   ├── integrations/
│   │   ├── auth_jwks.py
│   │   ├── retailer_client.py # JWT + internal modes
│   │   ├── utility_client.py  # NEW
│   │   ├── redis_client.py    # NEW
│   │   └── stt/               # NEW
│   ├── imports/               # NEW vision pipeline
│   ├── analytics/             # NEW pareto / slow movers
│   ├── forecasting/           # NEW
│   ├── alerts/                # NEW
│   ├── events/                # NEW RabbitMQ consumer
│   ├── workers/               # NEW async tasks
│   ├── db/                    # NEW when Postgres lands
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
