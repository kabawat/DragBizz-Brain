# 03 — Master Implementation Plan

Ordered build plan for **`dragbizz-ai`**.  
Product requirements come from `dragbizz-ai-service`; implementation follows **this repo’s current flow**.

Each step: **Objective → Sub-steps → Touches → Depends → DoD**.

---

## Golden build rules

1. Ship behind flags / env when risky (`AI_ENABLE_*`).
2. Tests before next step (unit + API where possible).
3. Prefer extending `ChatService` / `ToolRegistry` / `RetailerClient`.
4. Never write Mongo from AI.

---

## Phase A — Harden the current chat spine

### A1 — Second LLM synthesis turn ✅

**Objective:** Ground `message` in `toolResults` so users see numbers from tools, not invented text.

**Sub-steps**
1. After `execute_reads`, append assistant tool_calls + tool result messages (provider format).
2. Second `AiGateway.generate` **without** new tool calls (or tools disabled).
3. Pass synthesis output through `OutputGuard`.
4. Keep metrics: both turns’ tokens/latency.

**Touches:** `app/orchestrator/chat_service.py`, prompts, tests.

**Depends:** current chat.

**DoD:** “Aaj ki sale?” returns message that matches `toolResults` revenue; covered by `tests/unit/test_chat_synthesis.py`.

---

### A2 — Expand READ tools

**Objective:** Cover Phase-1 style sales intelligence via chat tools (and later REST wrappers).

**Add tools (examples)**
| Tool | Retailer source (illustrative) |
|---|---|
| `revenue_range` | analytics revenue for period |
| `top_sellers` | Pareto / top SKUs |
| `slow_movers` | velocity decline list |
| `low_stock` | stock below threshold |
| `customer_dues` | receivables |
| `search_customer` | customer search |

**Touches:** `app/tools/definitions.py`, `handlers/read_tools.py`, `RetailerClient`, routing eval JSON.

**DoD:** Each tool has schema + handler + unit test; chat can call them; storeId enforced.

---

### A3 — Provider adapters

**Objective:** Fail-over / task routing beyond OpenAI-compatible.

**Sub-steps:** Gemini adapter (+ optional Claude); router policy by env (`AI_ACTIVE_PROVIDER`, fallback list).

**Touches:** `app/providers/`, `ModelRouter`.

**DoD:** Switching env changes provider without chat API contract change.

---

## Phase B — Persistence & safety primitives

### B1 — Redis

**Objective:** Rate limit, idempotency keys, short-lived session cache.

**Touches:** `app/integrations/redis_client.py`, config, ready probe, middleware.

**DoD:** Per-tenant rate limit on `/chat`; idempotency helper usable by write tools.

---

### B2 — Postgres + Alembic (minimal)

**Objective:** Persist what Redis cannot: chat messages, jobs, alerts, usage.

**Initial models:** `ChatSession`, `ChatMessage`, `TokenUsage`, `IdempotencyRecord` (optional).

**Touches:** `app/db/`, `migrations/`, ready check.

**DoD:** Chat can optionally persist history by `sessionId`; migrations apply cleanly in compose.

---

### B3 — Internal auth

**Objective:** Service-to-service + webhook security parity with Node.

**Touches:** internal secret middleware, IP allowlist, `RetailerClient` dual mode (JWT vs secret).

**DoD:** Internal route rejects bad secret; user JWT path unchanged.

---

### B4 — Utility client

**Objective:** FCM, WhatsApp send, storage presign.

**Touches:** `app/integrations/utility_client.py`.

**DoD:** Dry-run/integration test against mocked utility.

---

## Phase C — Write tools & confirmation

### C1 — Invoice draft tool

**Objective:** `create_invoice_draft` (`ToolRisk.WRITE`) → retailer calculate + draft; return draft id + totals; **no release**.

**Chat contract extension**
- Response may include `pendingConfirmation: { type, draftId, summary }`.
- Follow-up message / `POST /api/v1/chat/confirm` releases with idempotency key.

**Touches:** write handlers, executor, chat schema, prompts.

**DoD:** Draft created; release only on confirm; double-confirm does not double-release (idempotent).

---

### C2 — Product bulk draft / PO draft tools

Same pattern as C1 for image-import approval and auto-PO.

---

## Phase D — Voice & media APIs

### D1 — `POST /api/v1/voice/transcribe`

STT (Sarvam primary / Whisper fallback) → return text; optional `continueChat=true` pipes into `ChatService`.

**Touches:** `app/api/v1/voice.py`, `app/integrations/stt/`, workers if long.

**DoD:** Audio → transcript; Hindi/Gujarati smoke fixture.

---

### D2 — Image import

`POST /api/v1/imports/image` → 202 job → vision extract → draft rows → merchant approve → retailer bulk.

**Touches:** `app/api/v1/imports.py`, `app/imports/`, worker task, Utility presign.

**DoD:** Job lifecycle + ≥ field accuracy target on fixture images.

---

## Phase E — Channels

### E1 — WhatsApp webhook

HMAC verify → map phone↔store → enqueue process → reuse ChatService / write tools → utility send.

**Touches:** `app/api/v1/webhooks.py`, session mapping table, workers.

**DoD:** Flow A from `docs/06_DATA_FLOWS.md` works in staging with Meta test number.

---

## Phase F — Analytics & proactive intelligence

### F1 — Analytics engine + insights API

Compute Pareto / slow-movers from retailer reads (+ optional feature cache in Postgres).

**APIs:** `/api/v1/insights/*`, `/api/v1/dashboard/summary`.

Also expose as READ tools for chat.

---

### F2 — Workers + schedules

Daily summary, dead-stock scan, forecast batch — Redis-backed worker + beat.

---

### F3 — Event bus consumer

Consume `dragbizz.domain-events` → update caches / trigger alerts.

---

### F4 — Forecasting

Per-SKU forecast storage + `/api/v1/forecast/*` + chat tool.

---

### F5 — Alerts + Auto PO

Alert ledger + dedupe; PO draft generation with autonomy policy.

---

## Phase G — Governance & hardening

### G1 — Subscription entitlement gRPC/HTTP gate

### G2 — Token budget enforcement (beyond metrics log)

### G3 — Langfuse / Prometheus / OTel

### G4 — Eval harness (routing, faithfulness, OCR, MAPE)

### G5 — CI/CD, canary (`AI_ROLLOUT_MODE`), runbooks

---

## Suggested order (dependency graph)

```text
A1 → A2 → A3
A2 → C1 → C2
B1 → B3 → B4
B1 → B2 → C1
C1 → E1
D1 → E1
B4 → D2 → C2
A2 → F1 → F2 → F3 → F4 → F5
B2 → G2
F* + E* → G3 → G4 → G5
```

**First merchant-visible win after current chat:** A1 + A2 (better answers) then C1 (draft invoice).

---

## Definition of Done (global per phase)

- Unit tests + at least one API test
- Env vars documented in `.env.example` with `AI_` prefix
- Swagger updated
- No direct Mongo access
- Failure modes documented (degrade paths)
- Feature flag if writes or external channel
