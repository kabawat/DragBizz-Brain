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
- After a successful `create_invoice_draft`, chat also stages an
  `invoice_release` pending confirmation (short TTL)
- Bounded multi-round tool loop (`AI_CHAT_MAX_TOOL_ROUNDS`, default 3):
  after each round's results the LLM may chain the next tools, so
  "bill for <name> with <product>" finishes in ONE user turn
  (search customer + product -> draft -> pendingConfirmation).
  Repeated (tool, args) calls in a turn are skipped; the one-draft-per-turn
  guard spans rounds.
- Reply links are normalized: any invented domain in front of a
  `/dashboard/...` openPath is stripped so links stay relative/in-app
- RAG + input/output guards + synthesis + in-memory session history
- Invoice cancel / ledger delete / collect-link / NL "haan" confirm — deferred

## Ledger mapping (do not invert)

| AI tool | Retailer `type` | Effect |
|---|---|---|
| `ledger_credit` | `PAYMENT` | Customer paid us (due ↓, paid ↑) |
| `ledger_debit` | `DEBIT` | Customer owes more (due ↑) |

Idempotency: AI builds `ai:{sessionId}:{tool}:{hash(args)}`. Ledger sends it as
`idempotencyKey` to retailer; customer/invoice drafts use the in-process cache
(retailer invoice create has no idempotency key yet). Release confirmations use
the same cache keyed by confirmation id.

## Confirmation contract

Chat response may include:

```json
"pendingConfirmation": {
  "confirmationId": "...",
  "type": "invoice_release",
  "draftId": "...",
  "summary": { "total": 85, "currency": "INR" },
  "expiresAt": "ISO-8601"
}
```

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
