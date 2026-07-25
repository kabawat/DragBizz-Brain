# Feature: Image Product Import

## Goal

Catalogue/shelf photo → structured draft products → merchant approve → retailer bulk create.

## Pipeline

1. Auth JWT + entitlement check.
2. Presign upload via utility.
3. `ImportJob` row (Postgres) + enqueue worker.
4. Vision LLM (Gemini/GPT-4o) → JSON rows + confidence.
5. Normalize/dedupe; return for UI edit.
6. Approve → retailer bulk with idempotency.

## Modules

`app/api/v1/imports.py`, `app/imports/`, worker task, utility client.

## DoD

- 202 + poll API.
- No products created before approve.
- Accuracy target on fixture set (≥80% critical fields).
