# Feature: Forecasting, Alerts & Auto PO

## Goal

Proactive intelligence from ai-service Phases 3.

## Forecasting

- Nightly job per store/SKU → Postgres `Forecast`
- Features: history + festival calendar + weather (cached)
- API `/api/v1/forecast/*` + READ tool

## Alerts

- Triggers: events (`stock.low`, `batch.expiring`) + scheduled scans
- Dedupe hash; status lifecycle; notify via utility
- API `/api/v1/alerts`

## Auto PO

- Combine low stock + forecast + supplier mapping (retailer)
- Create **PO draft** only; merchant approve
- Autonomy policy per tenant later

## DoD

- Forecast beats naïve baseline on backtest sample.
- Alert fires once per dedupe window.
- PO draft maps to correct supplier on fixture data.
