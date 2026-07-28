# Feature: Chat & Tools

## Goal

Conversational Co-Partner for store questions and (later) confirmed actions, using the existing `ChatService` pipeline.

## Current

- `POST /api/v1/chat`
- READ tools: `search_product`, `today_sale`, `stock_summary`, `payment_history`
- WRITE tools (auto-exec): `create_customer`, `update_customer`,
  `create_invoice_draft`, `ledger_credit`, `ledger_debit`
- RAG + input/output guards + synthesis + in-memory session history
- No invoice release / cancel / delete; confirmation UX is Phase 5

## Ledger mapping (do not invert)

| AI tool | Retailer `type` | Effect |
|---|---|---|
| `ledger_credit` | `PAYMENT` | Customer paid us (due ↓, paid ↑) |
| `ledger_debit` | `DEBIT` | Customer owes more (due ↑) |

Idempotency: AI builds `ai:{sessionId}:{tool}:{hash(args)}`. Ledger sends it as
`idempotencyKey` to retailer; customer/invoice drafts use the in-process cache
(retailer invoice create has no idempotency key yet).

## Build

1. ~~**A1 Synthesis** — second LLM turn with tool results.~~
2. ~~**B2 Session memory** — multi-turn history.~~
3. ~~**C1 WRITE** — draft invoice + customer + ledger (auto-exec).~~
4. **A2 More READ tools** — revenue range, top sellers, slow movers, low stock, customer search/dues.
5. **Phase 5 confirm** — release / sensitive + FE confirm UX.
6. Optional stream later / Redis-backed sessions + idempotency.

## Implementation notes

- Register tools only via `ToolRegistry`.
- `storeId` in tool args must equal request `storeId` (validator already).
- Prompts: live numbers → tools only; docs → how-to only; never invent IDs.
- Add eval cases to `tests/eval/routing_cases.json`.

## DoD

- ~~Synthesis grounded in toolResults (output guard enforce mode test).~~
- ~~Write tools + duplicate idempotency tests.~~
- New READ tools covered by unit tests.
- Invoice **release** requires confirm (Phase 5).
