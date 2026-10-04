# DragBizz AI Service

FastAPI service that powers DragBizz chat: authenticated store Q&A, RAG over product docs, and retailer tool calls (sales, stock, customers, invoices). It does not talk to DragBizz databases directly — tools call approved business APIs with the caller's JWT and store scope.

## Setup

1. Copy env and install deps:

```bash
cp .env.example .env
./setup.sh
```

2. Fill required values in `.env`:

| Env | Purpose |
|---|---|
| `AI_OPENAI_API_KEY` | Embeddings (+ OpenAI chat fallback) |
| `CHEAPER_INFERENCE_API_KEY` | Primary chat provider (optional) |
| `AI_BASE_URL` | Nginx base (`http://dragbizz.local`) for `/auth` and `/retailer` |
| `AI_QDRANT_URL` | Qdrant URL (`http://localhost:6333` local; `http://qdrant:6333` in Docker) |
| `AI_REDIS_URL` | Optional; sessions, usage, model selection (empty = in-process) |

3. Run:

```bash
./run.sh                 # Docker: Redis + Qdrant + AI on :4004
./run.sh --index         # same, then index knowledge/
./run.sh --normal        # local .venv + uvicorn --reload
./run.sh --normal --index
```

Or:

```bash
docker compose up --build
```

4. Index docs (needs OpenAI key + Qdrant):

```bash
python -m app.rag.indexer
# production:
docker compose exec dragbizz-ai python -m app.rag.indexer --yes
```

## Endpoints

| URL | Notes |
|---|---|
| `http://localhost:4004` | API |
| `/docs` | Swagger |
| `/api/v1/health` | Public |
| `/api/v1/ready` | Public |
| `POST /api/v1/chat` | Auth required (Bearer or `at` cookie) |

## Chat smoke test

```bash
curl -sS -X POST "http://localhost:4004/api/v1/chat" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Aaj ki sale kitni hai?",
    "sessionId": "session-abc",
    "storeId": "507f1f77bcf86cd799439011",
    "language": "hi-IN"
  }'
```

## Lint

```bash
source .venv/bin/activate
ruff check .
```
