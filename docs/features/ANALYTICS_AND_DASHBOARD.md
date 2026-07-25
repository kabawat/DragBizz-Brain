# Feature: Analytics, Dashboard & Insights

## Goal

Read-only sales intelligence from `dragbizz-ai-service` Phase 1 — without blocking chat.

## Product requirements (from ai-service)

- Pareto 80/20 (revenue/margin)
- Slow-mover / dead-stock detection
- Daily AI narrative summary per store
- Dashboard widgets API for apk / store-fe

## How to implement here

1. `app/analytics/` pure functions over retailer payloads (or cached snapshots).
2. `RetailerClient` methods for analytics/inventory/batch reads.
3. REST: `/api/v1/insights/*`, `/api/v1/dashboard/summary`.
4. Mirror key insights as **READ tools** so chat can answer the same questions.
5. Cache summary in Redis/Postgres; refresh via worker schedule (Phase F2).
6. Optional: event consumer keeps feature cache warm (F3).

## DoD

- Insights match spreadsheet check on seed store.
- Dashboard p95 acceptable when cached.
- Chat tools return same underlying metrics.
