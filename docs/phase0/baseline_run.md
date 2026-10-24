# Phase 0 Baseline Run Record

**Run date:** 24 October 2026

**Environment:** Local Brain Docker service + signed-in `dragbizz.local` dashboard

**Data handling:** Read-only UI prompt; no business record created or modified.

## Capability and knowledge baseline

- Generated the inventory from the runtime tool registry: **50 registered tools** across **6 domains** (Khata 21, Sales 9, Inventory 6, Finance 6, Procurement 5, General 3).
- Read/write classification: 33 read tools and 17 write-access tools; 12 sensitive tools are marked confirmation-required.
- Generated a hash/chunk manifest for **56 checked-in knowledge files**.
- Recorded 18 slash commands observed in the previous local UI audit. Their tool associations remain candidate mappings until the frontend command handler is traced.
- Added 14 regression prompts linked to the audit finding set, expected behavior, oracle and local fixture checks.
- Added resettable JSON fixtures for two synthetic tenants, owner/read-only roles, overlapping record IDs, duplicate customers, Hinglish product aliases, stock edges, invoices, expenses, cashbook, suppliers/bills, purchase orders, payments, GST, staff, pagination, empty results, dependency failure and permission denial.

## Local end-to-end check

### Reproduction before routing fix

Prompt: `store ka naam kya hai`

Observed: the domain-routing path offered `store_brief`; that call timed out and chat returned a technical-error message. This did not answer the store-profile question.

### Result after routing fix

The store-profile intent now routes directly to `list_stores` in both routing modes. A fresh local dashboard chat returned **Malani Mart** and its **grocery** category. No record was changed.

## Automated checks

- `pytest -q`: **532 passed**.
- Focused discovery/governance/dossier/Phase 0 suite: **186 passed**.
- `ruff check` on changed Python files: **passed**.
- Local Brain `/api/v1/health`: **ok**.
- Local Brain `/api/v1/ready`: **ready**; HTTP client, AI provider and Qdrant reported ready.
- Whole-repository `ruff check .`: currently reports **235 pre-existing lint findings** across untouched files. These are outside Phase 0; changed Python files pass the same Ruff rules.

## Scope boundaries

- The synthetic dataset is a local, deterministic test fixture; it is not provisioned into a separate Core database. The current local dashboard smoke used the already configured local store, read-only.
- Inventory generation proves startup registry wiring and declared metadata. It does not prove per-user authorization or downstream success for all 50 operations.
- The knowledge manifest proves checkout content and deterministic chunking, not production Qdrant index freshness or retrieval provenance for an individual answer.
- Slash command mappings, indirect handler/API edges, a two-tenant API boundary run, and full browser regression for every capability remain to be verified in later phases or an isolated Core-backed staging environment.

## Closure decision

The Phase 0 local baseline artifacts and local smoke/regression checks are complete. External Core-backed staging provisioning and exhaustive route/API evidence remain explicitly unverified; do not interpret this baseline as certification that all 50 operations execute correctly.
