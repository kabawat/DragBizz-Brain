# 01 — Gap Analysis

Baseline: `dragbizz-ai` @ `feature/ai-voice-foundation`.  
Target: full Co-Partner surface described by `dragbizz-ai-service`.

Legend: **Done** · **Partial** · **Missing**

---

## Foundation

| Capability | Status | Notes |
|---|---|---|
| FastAPI factory + lifespan | Done | `app/main.py`, `app/lifespan.py` |
| Health / ready | Done | `/api/v1/health`, `/api/v1/ready` (+ Qdrant) |
| Request ID + JSON logs | Done | middleware + chat metrics log |
| JWKS auth | Done | Bearer + cookie |
| Internal secret + IP allowlist | Missing | Needed for webhooks / service-to-service & some retailer internal routes |
| Settings (`AI_*`) | Done | `app/config.py` |
| Redis (rate limit, idempotency, sessions) | Missing | README explicitly deferred |
| Postgres (sessions, jobs, alerts, forecasts, usage) | Missing | Add when persistence/async required |
| Observability (Prometheus / OTel / Langfuse) | Partial | Structured chat metrics only |
| CI/CD + eval harness | Partial | pytest/ruff; no full pipeline/evals suite like service |

## Chat & orchestration

| Capability | Status | Notes |
|---|---|---|
| `POST /api/v1/chat` | Done | Auth + storeId |
| Provider-agnostic router | Partial | OpenAI-compatible only |
| READ tools auto-execute | Done | 4 tools |
| WRITE / SENSITIVE tools + confirmation | Missing | Enum exists; executor refuses non-READ |
| Second LLM turn (ground message in toolResults) | Missing | Explicit in README |
| Conversation history persistence | Missing | `sessionId` accepted, not stored |
| Streaming chat (WS/SSE) | Missing | |
| Input / output guards | Done | log/enforce modes |
| RAG docs + citations | Done | Qdrant + knowledge/ |

## Tools (retailer-backed)

| Tool / intent (from service) | Status |
|---|---|
| search_product | Done |
| today_sale / revenue | Partial (`today_sale` only) |
| stock_summary | Done |
| payment_history | Done |
| get_top_sellers / Pareto | Missing |
| get_customer_dues / low_stock detail | Missing |
| create_invoice_draft / release | Missing |
| create_po_draft | Missing |
| send_reengagement / discount suggest | Missing |

## Channels & media

| Capability | Status |
|---|---|
| `/voice` STT | Missing |
| `/image` or imports pipeline | Missing |
| `/document` | Missing |
| WhatsApp webhook + session map | Missing |
| Utility client (FCM, WA, S3 presign) | Missing |

## Intelligence layer

| Capability | Status |
|---|---|
| Analytics engine (Pareto, slow movers) | Missing |
| Dashboard / insights APIs | Missing |
| Daily AI summary job | Missing |
| Demand forecasting | Missing |
| Proactive alerts + dedupe ledger | Missing |
| Domain-event consumer | Missing |
| Auto purchase orders | Missing |

## Governance

| Capability | Status |
|---|---|
| Subscription entitlement gate | Missing |
| Token budget / cost ledger | Partial (est_cost in metrics log only) |
| Canary / rollout flags | Missing |

---

## Summary

**Strengths to keep:** chat path, guards, RAG, tool schema validation, retailer JWT forwarding, provider abstraction.

**Largest gaps:** write tools + confirmation, persistence/Redis, async workers, WhatsApp/voice/vision, analytics/forecast/alerts, subscription gating.

**Strategy:** close gaps by **extending** existing modules (`tools/`, `orchestrator/`, `integrations/`, `api/v1/`) rather than cloning the service repo layout.
