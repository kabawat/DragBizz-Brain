# 00 — Vision & Golden Rules

## Vision

`dragbizz-ai` becomes the **only** DragBizz AI microservice: the Co-Partner for chat, voice, WhatsApp, analytics, forecasting, image import, alerts, and draft business actions.

`dragbizz-ai-service` remains the **product & architecture reference**. New work ships in **`dragbizz-ai`**, using this repo’s existing orchestration style.

## What we are building (merchant outcomes)

| Capability | Merchant value |
|---|---|
| Conversational AI | Ask store questions in en/hi/gu/hinglish; get grounded answers |
| Voice | Speak → STT → same chat/tool path |
| WhatsApp channel | Voice/text → draft invoice → confirm → release |
| Sales intelligence | Pareto, slow movers, daily AI summary, dashboard widgets |
| Demand forecast | Per-SKU demand with festival/weather overlays |
| Image import | Catalogue photo → draft products → approve → retailer bulk create |
| Proactive alerts | Low stock, expiry, dead-stock → FCM / WhatsApp |
| Auto PO | Low stock + forecast → PO **draft** → merchant approve |
| Cost / subscription | Entitlement gate + token budget per agency |

## Golden rules (never violate)

1. **Propose, never mutate core data directly.** No Mongo writes from AI. Drafts/calculations via `dragbizz-retailer`; retailer enforces GST, FIFO, RBAC, quota, immutability.
2. **Whitelisted tools only.** LLM may only call tools in `app/tools/` with JSON Schema validation (`ToolCallValidator`).
3. **Tenant scope everywhere.** `agencyId` / `storeId` on every tool call, cache key, session, vector filter, job.
4. **Identity preserved.** End-user JWT verified via JWKS; retailer calls use **forwarded user JWT** (current pattern) and/or internal secret where Node contracts require it.
5. **Confirmation for money/stock.** `ToolRisk.WRITE` / `SENSITIVE` never auto-commit; return pending confirmation or draft id first.
6. **Idempotency on every write propose.** `Idempotency-Key` on draft/release/bulk/PO.
7. **Graceful degrade.** RAG/Qdrant/LLM/retailer failure must not brick POS; chat degrades (empty docs, tool error payloads, clear messages).
8. **Extend current flow.** Prefer growing `ChatService` → `AiGateway` → `ToolExecutor` → `RetailerClient` over introducing a second parallel “agent runtime” unless a phase DoD requires it.

## Decision filter (when ai-service and this repo disagree)

| Topic | Prefer |
|---|---|
| Orchestration | Keep **ChatService + tool registry** (here). Add explicit state only when multi-turn confirm / WhatsApp needs it. |
| Vectors | Keep **Qdrant** for docs RAG. Add Postgres later only for sessions/jobs/alerts/forecasts — not to replace Qdrant unless scale forces it. |
| LLM | Keep **provider adapters** (`app/providers/`) + `ModelRouter`. Add Gemini/Claude as new adapters, not a new stack. |
| Async | Add Redis + worker process when jobs exceed request timeout (voice, OCR, nightly analytics) — mirror Celery *role*, implement with lightest fit (e.g. ARQ/Celery later). |
| Events | Subscribe to retailer domain events when proactive features need them; do not poll Mongo. |
| API prefix | Stay on **`/api/v1/*`** (this repo). Gateway may map `/ai/*` → this service. |

## Non-goals

- Replacing `dragbizz-retailer` business logic
- Blocking offline POS sync on AI availability
- Free-form agents that can invent HTTP calls
- Porting `dragbizz-ai-service` code file-for-file without adapting to this architecture
