# Phase 0 — Reproducible Baseline

This directory records the startup tool catalogue, observed UI command surface, RAG knowledge file manifest, and audit-derived regression corpus. The fixture at `tests/fixtures/phase0/staging_dataset.json` is synthetic and suitable for deterministic local tests; it is not inserted into any merchant database.

## Generate the capability inventory

From the Brain repository root:

```bash
source .venv/bin/activate
python scripts/generate_phase0_inventory.py
```

This writes `capability_inventory.json`, `capability_inventory.md`, and `knowledge_inventory.json`. The tool inventory comes from the runtime `ToolRegistry`, including handler, directly referenced `RetailerClient` methods, schema, risk, confirmation and permission metadata. The knowledge manifest records source path, SHA-256, size and deterministic chunk count. UI slash commands are in `ui_surface_inventory.json` based on the earlier signed-in UI observation.

The inventory deliberately distinguishes startup registration from effective user authorization and execution verification. Direct handler-call extraction can miss indirect calls. UI command-to-tool mappings are candidates only and remain unverified until traced through the frontend and runtime.

## Run the local baseline cases

```bash
source .venv/bin/activate
pytest -q tests/test_phase0_baseline.py tests/test_tool_discovery_matrix.py tests/test_tool_governance.py tests/test_customer_dossier.py
ruff check scripts/generate_phase0_inventory.py tests/test_phase0_baseline.py
```

The Phase 0 tests validate inventory drift, sensitive-tool confirmation metadata, synthetic tenant fixture boundaries, duplicate IDs across stores, Hinglish product aliases, stock edge cases, invoice pagination data, expense arithmetic, cashbook arithmetic, and supplier-bill/PO separation. Existing tests cover intent discovery, dossier behavior and tool-selection governance. Fixture checks validate test-data readiness; they are not yet end-to-end Core API or browser executions.

## What this baseline does not prove

- The JSON fixture is not a live seeded Core tenant. It is a deterministic contract fixture for local tests; full API/UI validation still requires an isolated staging Core environment.
- Inventory generation proves definitions and handlers are wired in the startup registry; it does not prove that a role is authorized or that a remote API works.
- Existing discovery tests prove routing candidates for their listed prompts, not factual response correctness.
- The RAG file manifest proves which source files are in the checkout and how they chunk deterministically; it does not prove that production Qdrant is indexed to those hashes or that a query retrieved a particular source.
- Live Malani data must remain read-only during this phase.

## Next Phase 0 closure items

- Validate fixture provisioning against the designated isolated staging environment (if available) and record cleanup ownership.
- Manually link slash commands, prompt capability text, RAG corpus/version/filtering, and non-tool UI actions to their owners; the static runtime registry cannot infer these.
- Add the external Core/API and browser smoke evidence to the phase ledger before declaring the baseline complete.
