# Feature: Chat & Tools

## Goal

Conversational Co-Partner for store questions and (later) confirmed actions, using the existing `ChatService` pipeline.

## Current

- `POST /api/v1/chat`
- READ tools: `search_product`, `today_sale`, `stock_summary`, `payment_history`
- RAG + input/output guards
- No synthesis turn; no WRITE tools; sessionId not persisted

## Build

1. **A1 Synthesis** — second LLM turn with tool results.
2. **A2 More READ tools** — revenue range, top sellers, slow movers, low stock, customer search/dues.
3. **C1 WRITE** — `create_invoice_draft` + confirm endpoint.
4. Persist history (B2) keyed by `sessionId` + `storeId` + `userId`.
5. Optional stream later.

## Implementation notes

- Register tools only via `ToolRegistry`.
- `storeId` in tool args must equal request `storeId` (validator already).
- Prompts: live numbers → tools only; docs → how-to only (already).
- Add eval cases to `tests/eval/routing_cases.json`.

## DoD

- Synthesis grounded in toolResults (output guard enforce mode test).
- New READ tools covered by unit tests.
- Invoice draft requires confirm; release idempotent.
