# Feature: Chat & Tools

## Goal

Conversational Co-Partner for store questions and confirmed sensitive actions, using the existing `ChatService` pipeline.

## Current

- `POST /api/v1/chat`
- `POST /api/v1/chat/confirm` — approve/reject pending sensitive actions
- READ tools: `search_product`, `search_customer`, `today_sale`, `stock_summary`, `payment_history`
- WRITE tools (auto-exec): `create_customer`, `update_customer`,
  `create_invoice_draft`, `update_invoice_draft` (link customer / replace
  items on a draft), `ledger_credit`, `ledger_debit`
- SENSITIVE: `release_invoice` (stages `pendingConfirmation`; never auto-exec)
- `create_customer` on retailer 409 (duplicate phone/email) self-heals: it
  looks the customer up by that phone/email and returns the existing profile
  as success (`existing: true`), so the LLM always has a real customerId
- Draft → `invoice_release` pending confirmation (short TTL): after the
  tool loop, if a SENSITIVE call already staged `pendingConfirmation` in
  that turn, that wins and draft writes do **not** stage again. Otherwise
  the latest successful `create_invoice_draft` / `update_invoice_draft` in
  `reversed(all_write_results)` wins (so a later update’s totals refresh
  the preview). See `ChatService.handle` in `app/orchestrator/chat_service.py`.
- Bounded multi-round tool loop (`AI_CHAT_MAX_TOOL_ROUNDS`, default 3):
  after each round's results the LLM may chain the next tools, so
  "bill for <name> with <product>" finishes in ONE user turn
  (search customer + product -> draft -> pendingConfirmation).
  Repeated (tool, args) calls in a turn are skipped; the one-draft-per-turn
  guard spans rounds. After a successful `create_invoice_draft` /
  `update_invoice_draft`, the next LLM call is forced to synthesis
  (`tools` omitted) to skip re-sending tool schemas.
- `search_product` / `search_customer` return compact projections into the
  LLM context (not full retailer serializer docs). Action/live questions
  use a smaller RAG docs budget (`AI_RAG_CONTEXT_MAX_TOKENS_ACTION`,
  default 512); how-to questions keep `AI_RAG_CONTEXT_MAX_TOKENS`.
- Reply links are normalized: any invented domain in front of a
  `/dashboard/...` openPath is stripped so links stay relative/in-app
- RAG + input/output guards + synthesis + session history
  (Redis when `AI_REDIS_URL` is set; else in-process)
- Write idempotency + pending confirmations also use Redis when configured
  (fail-closed on Redis errors for those two; sessions fail-open)
- Invoice cancel / ledger delete / collect-link / NL "haan" confirm — deferred

## Ledger mapping (do not invert)

| AI tool | Retailer `type` | Effect |
|---|---|---|
| `ledger_credit` | `PAYMENT` | Customer paid us (due ↓, paid ↑) |
| `ledger_debit` | `DEBIT` | Customer owes more (due ↑) |

Idempotency: AI builds `ai:idempotency:{sessionId}:{tool}:{hash(args)}`.
Ledger sends it as `idempotencyKey` to retailer; customer/invoice drafts use
the AI idempotency store (Redis when configured). Release confirmations use
the confirmation store keyed by confirmation id.

## Confirmation contract

Chat response may include at most one `pendingConfirmation` per turn:

```json
"pendingConfirmation": {
  "confirmationId": "...",
  "type": "invoice_release",
  "draftId": "...",
  "summary": { "total": 85, "currency": "INR" },
  "expiresAt": "ISO-8601"
}
```

Staging priority: SENSITIVE `release_invoice` call (staged in the tool loop)
over draft-write auto-staging; among draft writes, latest successful create
or update wins.

Confirm body: `{ sessionId, storeId, confirmationId, draftId, action: "approve"|"reject" }`.

## Build

1. ~~**A1 Synthesis** — second LLM turn with tool results.~~
2. ~~**B2 Session memory** — multi-turn history.~~
3. ~~**C1 WRITE** — draft invoice + customer + ledger (auto-exec).~~
4. **A2 More READ tools** — revenue range, top sellers, slow movers, low stock, customer dues (~~customer search~~ done).
5. ~~**Phase 5 confirm** — release / sensitive + FE confirm UX.~~
6. Optional stream later / Redis-backed sessions + idempotency.
7. Deferred sensitive: invoice cancel, ledger delete, collect-link, NL confirm.

## Implementation notes

- Register tools only via `ToolRegistry`.
- `storeId` in tool args must equal request `storeId` (validator already).
- Prompts: live numbers → tools only; docs → how-to only; never invent IDs.
- Add eval cases to `tests/eval/routing_cases.json`.

## DoD

- ~~Synthesis grounded in toolResults (output guard enforce mode test).~~
- ~~Write tools + duplicate idempotency tests.~~
- New READ tools covered by unit tests.
- ~~Invoice **release** requires confirm (Phase 5).~~
