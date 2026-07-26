# Feature: Chat & Tools

## Goal

Conversational Co-Partner for store questions and (later) confirmed actions, using the existing `ChatService` pipeline.

## Current

- `POST /api/v1/chat`
- READ tools: `search_product`, `today_sale`, `stock_summary`, `payment_history`
- RAG + input/output guards
- Second LLM synthesis turn after tools (grounded `message`)
- In-memory session history (`sessionId` + user + store; TTL)
- No WRITE tools

## Build

1. ~~**A1 Synthesis** — second LLM turn with tool results.~~
2. ~~**B2 Session memory** — multi-turn history.~~
3. **A2 More READ tools** — revenue range, top sellers, slow movers, low stock, customer search/dues.
4. **C1 WRITE** — `create_invoice_draft` + confirm endpoint.
5. Optional stream later / Redis-backed sessions.

## Implementation notes

- Register tools only via `ToolRegistry`.
- `storeId` in tool args must equal request `storeId` (validator already).
- Prompts: live numbers → tools only; docs → how-to only (already).
- Add eval cases to `tests/eval/routing_cases.json`.

## DoD

- ~~Synthesis grounded in toolResults (output guard enforce mode test).~~
- New READ tools covered by unit tests.
- Invoice draft requires confirm; release idempotent.
