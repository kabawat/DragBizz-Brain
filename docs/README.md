# DragBizz AI — Complete Build Docs

> **Product target:** Full AI Co-Partner capabilities defined in `dragbizz-ai-service`.  
> **Implementation home:** **this repo only** (`dragbizz-ai`).  
> **Constraint:** Extend the **current** `dragbizz-ai` flow (ChatService → providers → tools → retailer), do not re-port LangGraph/Celery/Postgres wholesale unless a phase explicitly requires it.

Source of product truth (read for *what* merchants need):

| Upstream doc (ai-service) | Use for |
|---|---|
| `AI_ARCHITECTURE.md` | System role, golden rules, ecosystem placement |
| `AI_ROADMAP.md` | Phased product outcomes |
| `DATA_FLOW.md` | WhatsApp invoice, image import, proactive alerts |
| `BACKEND_DEVELOPMENT_PLAN.md` | Feature checklist / DoD ideas |
| `docs/AI_COMPLETE_GUIDE_*.md` | End-to-end feature inventory |

These docs translate that product into **how we build it here**.

---

## Doc index

| File | Purpose |
|---|---|
| [00_VISION_AND_GOLDEN_RULES.md](./00_VISION_AND_GOLDEN_RULES.md) | Vision, non-negotiables, decision filter |
| [01_GAP_ANALYSIS.md](./01_GAP_ANALYSIS.md) | What exists today vs full Co-Partner |
| [02_ARCHITECTURE_MAPPING.md](./02_ARCHITECTURE_MAPPING.md) | Map ai-service concepts → this repo modules |
| [03_MASTER_IMPLEMENTATION_PLAN.md](./03_MASTER_IMPLEMENTATION_PLAN.md) | Ordered build steps + DoD (primary plan) |
| [04_API_SURFACE.md](./04_API_SURFACE.md) | Target REST/WS surface under `/api/v1` |
| [05_MODULE_LAYOUT.md](./05_MODULE_LAYOUT.md) | Target folders extending current tree |
| [06_DATA_FLOWS.md](./06_DATA_FLOWS.md) | Critical flows adapted to current orchestrator |
| [features/](./features/) | Per-capability specs (chat, analytics, voice, …) |
| [flows/](./flows/) | Deep-dive sequence notes |

---

## How to use this pack

1. Read **00** + **01** once (context + gaps).
2. Before coding any feature, read **02** (where the code goes) + the matching **features/** doc.
3. Execute **03** in order — each step lists touches, deps, and Definition of Done.
4. Keep APIs aligned with **04**; keep folder growth aligned with **05**.

---

## Current baseline (already in this repo)

- FastAPI app + lifespan, `/api/v1/health`, `/api/v1/ready`
- JWKS auth (Bearer / cookie)
- OpenAI-compatible provider + `ModelRouter`
- Qdrant RAG (`knowledge/` → indexer → retriever → chat prompt)
- Input / output guards
- `POST /api/v1/chat` with allowlisted **READ** tools executed via retailer + user JWT
- Tool risk enum already has `read` | `write` | `sensitive` (write path not wired yet)

Port: **4004** locally (compose). Auth/retailer via gateway URLs.
