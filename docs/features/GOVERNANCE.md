# Feature: Governance (Subscription, Cost, Observability)

## Goal

Production controls from ai-service Steps 19–20.

## Subscription

- Before expensive AI routes: check entitlement (gRPC/HTTP to subscription svc).
- Return `FEATURE_NOT_AVAILABLE` when disabled.

## Cost

- Persist token usage per agency/store (extend chat metrics).
- Enforce monthly budget → `QUOTA_EXCEEDED`.
- Provider fail-over when primary errors.

## Observability

- Prometheus `/api/v1/metrics`
- Optional OTel + Langfuse traces on LLM/tool spans
- Keep PII out of logs (current chat metrics policy)

## Rollout

- `AI_ROLLOUT_MODE` / agency allowlist for canary
- **Guards:** `AI_INPUT_GUARD_MODE` / `AI_OUTPUT_GUARD_MODE` must be `enforce`
  when `AI_ENVIRONMENT=production` (validated at settings load). Staging should
  stay on `log` until false positives are tuned — see [GUARDS.md](./GUARDS.md).

## DoD

- Prod refuses boot without critical env (optional strict mode).
- Prod refuses boot unless both guards are `enforce` (done).
- Budget denial path tested.
- Dashboards/runbooks linked from README.
