# DragBizz Voice AI — Implementation TODO

**Goal:** Ship a provider-independent voice/text AI orchestrator that never talks to business databases directly. All business data moves through existing microservice APIs (`auth`, `retailer`, `utility`, `subscription`) with the caller's JWT and store scope preserved.

**Rules:** Follow [docs/rule.md](../docs/rule.md) and [FE/rule.md](../FE/rule.md) — impact analysis before each phase, no temporary fixes, no duplicate logic, security first.

**Related:** [DragBizz_AI_Voice_Architecture_Recommended.md](../DragBizz_AI_Voice_Architecture_Recommended.md) · [dragbizz-ai/README.md](./README.md)

**Branch suggestion:** `feature/ai-voice-foundation`

**Last reviewed:** July 2026

---

## Impact Analysis (global)

| Area | Impact |
|---|---|
| **Services** | New `dragbizz-ai`; calls into `dragbizz-auth` (JWKS), `dragbizz-retailer` (tools), `dragbizz-utility` (optional upload/notify), reverse-proxy `/ai` route |
| **APIs** | New `POST /api/v1/chat` (and later voice/admin); retailer endpoints reused as tools — no business schema changes required for read tools |
| **Database** | AI must **not** own customer/invoice/ledger/product data. Optional AI-only stores: conversation sessions, AI usage/audit logs, admin model config cache |
| **Frontend** | `dragbizz-store-fe` voice launcher → AI text API; later desktop Electron path |
| **Permissions / roles** | Reuse retailer `permissionCheck` + `verifyStoreAccess` via forwarded user JWT; AI tool allowlist + risk tiers |
| **Background jobs** | Later: token/cost aggregation, session cleanup, optional backend STT jobs (BullMQ/Redis — not RabbitMQ) |
| **Tests / docs** | Unit + integration per phase; update architecture doc status as phases ship |

### Hard constraints

- LLM never accesses Mongo/business DB directly.
- Tool Executor only calls allowlisted HTTP/gRPC clients.
- Forward end-user JWT (no elevating service account for writes).
- Sensitive money/stock actions require confirmation before execute.
- Idempotency keys on write tools that may retry.

---

## Status snapshot

```
DONE   Phase 0  Frontend voice capture + global UI (store-fe)
DONE   Phase 0  dragbizz-ai FastAPI skeleton (health, logging, router contracts)
DONE   Phase 1  Auth (JWKS) + POST /api/v1/chat (text-only stub)
DONE   Phase 2  First real provider + structured tool calling
DONE   Phase 3  Read-only retailer tools
DONE   Phase 3.5 Grounded answers + session memory + guard enforce
DONE   Phase 4  Write tools + idempotency
THEN   Phase 5  Sensitive tools + voice confirmation UX
DONE   Phase 6  Frontend wire-up (transcript → AI)
THEN   Phase 7  Admin model switch + cost limits + observability
LATER  Phase 8  Backend STT fallback, TTS, desktop, streaming, vision
```

---

## Phase 0 — Foundation (completed)

### Frontend (store-fe)

- [x] `hooks/media/useVoiceCapture.js` — mic, constraints, RMS VAD, browser STT
- [x] `components/voice/VoiceCommandLauncher.jsx` — global launcher, drag, theme tokens, no box-shadow
- [x] i18n `voice.json` (en / hi / hi-en / gu)
- [x] Mount in dashboard layout

### AI service skeleton

- [x] FastAPI app factory, lifespan, config (`AI_` prefix)
- [x] `/api/v1/health`, `/api/v1/ready`
- [x] Request ID middleware, JSON logging, error handlers
- [x] `ModelProvider` base + `ModelRouter` + `AiGateway`
- [x] `ToolRegistry` + tool risk schema (`read` / `write` / `sensitive`)
- [x] Docker (host `:3000`), local (`:4004`), tests, README

---

## Phase 1 — Secure text entry (P0) ✅

**Why:** Without auth + a chat entrypoint, frontend cannot safely talk to AI.

### Impact (phase)

- Files: `app/core/security.py`, `app/api/v1/chat.py`, `app/schemas/chat.py`, `app/integrations/auth_jwks.py`, `app/api/dependencies.py`
- APIs: `POST /api/v1/chat`
- Services: Auth JWKS; no retailer yet
- Frontend: none yet (contract only)
- DB: none

### TODO

- [x] Add JWKS verification against Auth `/.well-known/jwks.json` (issuer/audience/clock skew)
- [x] Dependency: require `Authorization: Bearer` on chat (health/ready stay public)
- [x] Request DTO: `text`, `sessionId`, `storeId`, `language`
- [x] Response DTO: `message`, `sessionId`, `requestId`, `userId` (stub message; no tools)
- [x] Reject missing/invalid `storeId` early
- [x] Propagate `X-Request-ID`
- [x] Rate limit per user/tenant — **deferred** (no Redis yet; documented in README)
- [x] Unit tests: valid JWT path, expired JWT, invalid JWT, invalid storeId
- [x] Update README with auth contract

### Risks

- Wrong issuer/audience breaks all clients
- Skipping JWT and using a service token would bypass RBAC later

---

## Phase 2 — Provider + structured tool calls (P0) ✅

**Why:** Business logic must not depend on a single vendor; tools need a stable JSON contract.

### Impact (phase)

- Files: `app/providers/openai_compatible.py`, `app/orchestrator/chat_service.py`, `app/orchestrator/tool_call_validator.py`, `app/prompts/system/chat.py`, `app/tools/definitions.py`
- APIs: chat returns `toolCalls` / assistant text / `provider` / `model`
- Secrets: provider keys only in env (never commit)
- DB: none — active provider from env only

### TODO

- [x] Implement one production provider adapter first (OpenAI-compatible)
- [x] Normalize tool-call schema across providers (name + args JSON)
- [x] Prompt builder: system rules — allowlisted tools only, never invent IDs
- [x] JSON schema validation + repair/retry loop on malformed tool args
- [x] Model router: register + `set_active` from config
- [x] Timeout / max_tokens caps per request
- [x] Unit tests: fake provider, malformed tool JSON, router active selection
- [x] Document provider env vars in `.env.example` (names only, no secrets)

### Notes

- Tool **execution** / retailer HTTP remains Phase 3 (`toolResults` not returned yet).
- Read-tool definitions only: `search_product`, `today_sale`, `stock_summary`, `payment_history`.

### Risks

- Provider tool-calling differences break “easy switching” without normalization
- Unbounded tokens = cost explosion

---

## Phase 3 — Read-only tools via retailer HTTP (P0) ✅

**Why:** Prove no-DB design with safe auto-exec tools.

### Impact (phase)

- Files: `app/integrations/retailer_client.py`, `app/tools/handlers/read_tools.py`, `app/executors/tool_executor.py`, `app/tools/context.py`
- APIs called: `GET /product`, `GET /analytics/revenue`, `GET /analytics/stock`, `GET /customer-account/payments`
- Permissions: retailer middleware still enforces with forwarded JWT
- Frontend: none required
- Chat response: `toolResults` added; second LLM synthesis turn ships in Phase 3.5 A1

### TODO

- [x] `RetailerClient` with base URL from `AI_RETAILER_SERVICE_URL`
- [x] Always forward user JWT + `store` query consistently (`req.store` pattern)
- [x] Register tools:
  - [x] `search_product`
  - [x] `today_sale`
  - [x] `stock_summary`
  - [x] `payment_history`
- [x] Mark all as `ToolRisk.READ` — auto-exec after validation
- [x] Map tool errors to stable AI error codes (403/404/429; 401 fails chat)
- [x] Integration tests with mocked retailer HTTP
- [x] Update architecture doc tool mapping with exact paths

### Risks

- Store query vs body mismatch (known retailer footgun) — always set `?store=` on GETs
- Owner JWT bypasses staff RBAC — still rely on retailer checks; keep tool allowlist tight

---

## Phase 3.5 — Grounded answers + session + guard harden (P0)

**Why:** Close the biggest product gaps after read tools: answers must use live tool data, multi-turn context must work, and guards must protect in production — not only log.

Related detail: [docs/features/CHAT_AND_TOOLS.md](./docs/features/CHAT_AND_TOOLS.md) (A1), [docs/03_MASTER_IMPLEMENTATION_PLAN.md](./docs/03_MASTER_IMPLEMENTATION_PLAN.md).

### Impact (phase)

- Files: `app/orchestrator/chat_service.py`, `app/prompts/*`, `app/guards/*`, optional session store (Redis/Postgres later)
- APIs: chat `message` is post-tool synthesis when tools ran; `sessionId` loads prior turns
- Config: `AI_INPUT_GUARD_MODE` / `AI_OUTPUT_GUARD_MODE` → `enforce` for production
- Frontend: can keep showing `message`; tool result panel still optional
- DB: optional short-lived session history (not business data)

### TODO

#### A1 — Second LLM synthesis turn

- [x] After tool execution, run a second LLM call with `toolResults` (and RAG context) so `message` is grounded in live numbers — not the first speculative reply
- [x] Pass synthesis output through `OutputGuard`
- [x] Cap synthesis tokens; skip second call when there were no tool calls
- [x] Tests: tool amounts appear in `message`; invented ₹ amounts still caught by output guard

#### B2 — Session / multi-turn memory

- [x] Persist chat turns keyed by `sessionId` + `userId` + `storeId` (start with in-memory or Redis TTL; Postgres if durable history needed)
- [x] Load prior turns into the next `GenerationRequest` (bounded window / token budget)
- [x] Echo `sessionId`; reject cross-user/store session reuse
- [x] Tests: follow-up question uses prior tool/context; TTL expiry clears history

#### Guard enforce rollout

- [x] Document when to set `AI_INPUT_GUARD_MODE=enforce` and `AI_OUTPUT_GUARD_MODE=enforce` (prod default target)
- [x] In production settings validation (or deploy docs): warn/require enforce for both guards
- [x] Secret scrub stays redaction-friendly; unsupported-currency path returns safe fallback in enforce mode
- [x] Tests: enforce input refusal schema; enforce output redaction / blocked unsupported amounts

### Risks

- Synthesis without token caps doubles cost/latency per tool-using turn
- Session store without authz binding leaks another user's chat
- Enforce too early on noisy regex guards → false-positive refusals; tune in `log` first, then flip

---

## Phase 4 — Write tools + idempotency (P1)

**Why:** Voice retries and network timeouts must not duplicate customers/invoices/ledger rows.

### Impact (phase)

- APIs: `POST /customer`, `PUT /customer/:id`, `POST /invoices`, `POST /customer-account/transactions`
- Retailer: may need invoice create idempotency key if still missing
- Frontend: later confirmation UX for some writes

### TODO

- [x] Tools: `create_customer`, `update_customer`, `create_invoice_draft` (draft only)
- [x] Tools: `ledger_credit` → `PAYMENT`, `ledger_debit` → `DEBIT` (explicit mapping docs)
- [x] Always send `idempotencyKey` on ledger/payment; AI-side cache for invoice/customer (retailer has no invoice key)
- [x] Arg validation (phone, amount > 0, required fields)
- [x] Do **not** expose invoice release/cancel/delete in this phase
- [x] Audit log entry: `sessionId`, tool, user, store, outcome (AI-side)
- [x] Tests: duplicate submit same idempotency key

### Risks

- Ledger credit/debit naming inverted = wrong balances
- Invoice draft without idempotency = duplicate bills on voice retry

---

## Phase 5 — Sensitive actions + confirmation (P1)
**Why:** Money and stock must not execute from a single ASR pass.
### Impact (phase)

- APIs: invoice release/cancel, payment collect-link (only if explicitly approved)
- Frontend: confirmation step in `VoiceCommandLauncher`
- Permissions: owner/staff still enforced by retailer

### TODO

- [ ] Define sensitive tool set (release invoice, ledger delete, collect-link, etc.)
- [ ] Chat response: `requiresConfirmation: true` + preview payload
- [ ] Confirm endpoint or second chat turn with `confirmationToken`
- [ ] Frontend: confirm / cancel UI before execute
- [ ] Expire confirmation tokens (short TTL)
- [ ] Tests: execute without confirm rejected

### Risks

- Skipping confirmation for “speed” creates irreversible ledger/stock damage
---

## Phase 6 — Frontend wiring (P1) ✅

**Why:** Voice UI currently captures transcript but does not call AI.

### Impact (phase)

- Files: store-fe `service/ai/*`, `api.config.js`, `VoiceCommandLauncher.jsx`, `useAiVoiceChat.js`
- Backend: cookie `at` accepted alongside Bearer (web session)
- State: sessionId owned by `useAiVoiceChat`
- Desktop: out of scope unless explicitly scheduled

### TODO

- [x] Add `AI` block to `api.config.js` (`/brain` nginx path)
- [x] `aiChatService` with cookie auth via `authAxios`
- [x] On stop listening → `POST /brain/api/v1/chat` with `storeId` + `sessionId` + language
- [x] Show assistant reply + tool result summaries in panel
- [x] Handle `insecure_context` / permission errors (already partial)
- [ ] Wire confirmation UI for Phase 5 responses
- [x] Do not duplicate business logic in UI — hooks/services only

### Risks

- Proxy `/brain` not configured → 404 in env
- `http://dragbizz.local` insecure context blocks mic (HTTPS/localhost/flag)

---

## Phase 7 — Admin model switch + cost + observability (P2)

### TODO

- [ ] Admin API to select active provider/model (authz: platform/store admin only)
- [ ] Persist selection in AI config store / Redis cache
- [ ] Per-tenant token/cost counters and hard caps
- [ ] Metrics: latency, tool success rate, provider errors
- [ ] Audit trail for tool executions (immutable append)
- [ ] Docs: how ops rotates provider keys

---

## Phase 8 — Later / future (P3)

Keep out of critical path until Phases 1–6 are stable.

- [ ] Backend STT fallback (`POST /api/v1/voice`) + audio size limits
- [ ] Optional TTS
- [ ] Streaming responses (socket/SSE) with tool-call commit rules
- [ ] Desktop Electron: media permission, CSP/WASM, offline STT strategy
- [ ] Vision/OCR tools
- [ ] Multilingual Hinglish improvements beyond browser STT
- [ ] Local LLM (Ollama) adapter with constrained JSON

---

## Explicitly out of scope for AI service

- Direct Mongo access to `dragbizz_retailer` / auth business collections
- Bypassing `permissionCheck` / `verifyStoreAccess`
- Auto-executing invoice release, deletes, or payment collect without confirmation
- Committing provider API keys into git
- Duplicating retailer domain logic inside AI prompts as the source of truth

---

## Definition of done (per phase)

- [ ] Impact analysis reviewed for that phase
- [ ] Request/response contracts inspected against real retailer/auth APIs
- [ ] Validation + authz in place
- [ ] Unit (and integration where HTTP) tests green
- [ ] No dead code / unused stubs left behind
- [ ] README / architecture doc status updated
- [ ] No secrets in repo

---

## Suggested next action

Start **Phase 5**: sensitive tool confirmation UX (invoice release, etc.) — ledger/money tools can move to `SENSITIVE` + confirm when ready.
