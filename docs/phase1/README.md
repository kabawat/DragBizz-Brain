# Phase 1 — Privacy, tenant isolation and authorization

## Delivered

- Chat, streamed chat, confirmation, chat-session, and notification endpoints
  now verify requested store access with Core using the verified bearer token.
  Core checks owner/staff assignment; a request parameter alone cannot grant
  access to another store. Signed store claims, when present, further restrict
  the selected store.
- When verified claims include per-store or user permissions, tool schemas are
  narrowed to tools whose complete declared permission set is present. The
  downstream DragBizz Core API remains the final authorization boundary for
  each retailer operation.
- Customer search no longer returns phone or email unless requested. Ambiguous
  customer and supplier matches expose names only, without contact data, record
  IDs, addresses, balances, or other candidate details.
- Customer account lists, top-customer rankings, invoice/customer references,
  sales-order/customer references, and staff lists omit unrequested contact
  fields. Phone/email are retained for account lists and top-customer results
  only when the prompt explicitly requests them.
- Every tool now has a declared permission mapping; a regression test prevents
  new unclassified tools from entering the registry.

## Local verification

- Full Brain suite: **545 passed**.
- Touched Python files pass Ruff.
- API regressions exercise cross-store rejection for chat, streaming, confirm,
  session list, session detail, and session deletion.
- Privacy regressions cover exact customer search, explicit contact requests,
  duplicate customer names, duplicate suppliers, customer account lists, and
  role permission filtering.

### Final local run

- Full Brain suite: **545 passed**.
- Ruff checks and `git diff --check`: passed.
- Local browser chat passed store authorization and reached the model request,
  but the response ended with `Request aborted`; Brain logs show an upstream AI
  provider TLS `SSLV3_ALERT_BAD_RECORD_MAC`. The user-visible AI answer is not
  verified locally in this run.

## Security boundary and remaining proof

Brain now delegates store membership to Core for the actual Auth token format
(which carries user/role/agency claims, not store lists). Tool permissions in
claims narrow model-visible tools when present; Core remains authoritative for
each retailer operation. A local browser request reached the model after Core
authorization, but upstream AI TLS failed before an answer was returned.
Production has not yet been redeployed or smoke-checked in this phase. Indirect
prompt-injection cases and a full role matrix against two provisioned staging
tenants remain unverified.

## Regression catalog

See [regression_cases.json](regression_cases.json). Cases are safe, synthetic,
and run locally; they do not provision or mutate production business data.
