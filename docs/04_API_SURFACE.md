# 04 — Target API Surface

Keep prefix **`/api/v1`**. Nginx may expose as `/ai/*`.

Auth: JWT unless noted. All store-scoped routes require `storeId` (body/query) matching tenant access.

---

## Exists today

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/health` | public | liveness |
| GET | `/api/v1/ready` | public | deps (incl. Qdrant) |
| POST | `/api/v1/chat` | JWT | READ+WRITE tools auto-run; synthesis; `pendingConfirmation` |
| POST | `/api/v1/chat/confirm` | JWT | Approve/reject staged SENSITIVE action |
| GET | `/api/v1/admin/model` | platform admin | Active + allowed provider/model |
| PUT | `/api/v1/admin/model` | platform admin | Runtime model switch (persisted) |
| GET | `/api/v1/admin/usage/{storeId}` | platform admin | Daily per-tenant tokens/cost + caps |
| GET | `/api/v1/admin/metrics` | platform admin | Latency, provider errors, tool success rate |

---

## Target additions

### Chat

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/chat` | Extended: synthesis turn, pendingConfirmation |
| POST | `/api/v1/chat/confirm` | Confirm WRITE/SENSITIVE draft (idempotent) |
| GET | `/api/v1/chat/sessions/{id}` | History (after Postgres) |
| WS/SSE | `/api/v1/chat/stream` | Streaming tokens (later) |

### Voice / media

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/voice/transcribe` | STT → text (+ optional chat) |
| POST | `/api/v1/imports/image` | Start catalogue OCR job → 202 |
| GET | `/api/v1/imports/{jobId}` | Poll job + draft rows |
| POST | `/api/v1/imports/{jobId}/approve` | Bulk create via retailer |

### Insights / dashboard / forecast / alerts

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/dashboard/summary` | Cached daily summary + KPIs |
| GET | `/api/v1/insights/pareto` | 80/20 |
| GET | `/api/v1/insights/slow-movers` | Velocity decline |
| GET | `/api/v1/forecast/skus` | Demand horizon |
| GET | `/api/v1/alerts` | List / filter |
| POST | `/api/v1/alerts/{id}/ack` | Acknowledge |
| POST | `/api/v1/purchase-orders/draft` | Generate PO draft |

### Webhooks / internal

| Method | Path | Auth |
|---|---|---|
| GET/POST | `/api/v1/webhooks/whatsapp` | Meta HMAC |
| POST | `/api/v1/internal/*` | Internal secret (optional ops) |

### Ops

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/metrics` | Prometheus (Phase G) |

---

## Chat request/response evolution

**Request (keep compatible)**

```json
{
  "text": "string",
  "sessionId": "string",
  "storeId": "24-hex",
  "language": "hi-IN"
}
```

**Response additions (non-breaking)**

```json
{
  "message": "...",
  "sessionId": "...",
  "requestId": "...",
  "toolCalls": [],
  "toolResults": [],
  "pendingConfirmation": {
    "type": "invoice_release",
    "draftId": "...",
    "summary": { "total": 85, "currency": "INR" },
    "expiresAt": "ISO-8601"
  },
  "citations": [{ "source": "docs/...", "score": 0.81 }]
}
```

Confirm body:

```json
{
  "sessionId": "...",
  "storeId": "...",
  "confirmationId": "...",
  "draftId": "...",
  "action": "approve" 
}
```

---

## Error codes (extend existing)

Keep current: `AUTH_*`, `STORE_ID_*`, `TOOL_*`, `AI_PROVIDER_*`, `VALIDATION_ERROR`.

Add: `CONFIRMATION_REQUIRED`, `CONFIRMATION_EXPIRED`, `IDEMPOTENCY_CONFLICT`, `QUOTA_EXCEEDED`, `FEATURE_NOT_AVAILABLE`, `JOB_NOT_FOUND`, `WEBHOOK_INVALID_SIGNATURE`.
