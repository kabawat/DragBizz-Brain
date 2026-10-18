# DragBizz AI Service

The AI service handles DragBizz chat, including store-specific questions, product
documentation search, and business actions. It accesses business data through the
approved APIs, using the caller's JWT and store scope; it does not connect directly
to DragBizz databases.

## Requirements

- Python 3.11 or newer for local development
- Docker with the Compose plugin to run the full stack in containers

## Configure and install

From this directory, run:

```bash
./setup.sh
```

The script creates `.env` from `.env.example` if needed, creates `.venv`, and
installs the service and development dependencies. On Debian or Ubuntu, it also
installs the matching `python3-venv` package if Python reports that `ensurepip`
is unavailable; this may prompt for your sudo password.

Set the values you need in `.env` before starting the service:

| Variable | Purpose |
|---|---|
| `AI_ACTIVE_PROVIDER` | `google_ai`, `openai_compatible`, or `cheaper_inference` |
| `AI_GOOGLE_API_KEY` | Gemini chat when `AI_ACTIVE_PROVIDER=google_ai` |
| `AI_GOOGLE_MODEL` | Default `gemini-3.1-flash-lite` |
| `AI_OPENAI_API_KEY` | Embeddings, and chat when the active provider is OpenAI |
| `CHEAPER_INFERENCE_API_KEY` | Fallback chat provider |
| `AI_BASE_URL` | Base URL for the `/auth` and `/retailer` APIs |
| `AI_QDRANT_URL` | Qdrant URL; use `http://localhost:6333` locally |
| `AI_REDIS_URL` | Optional Redis URL; empty uses in-process storage |

## Run

Start the full stack with Docker Compose:

```bash
./run.sh
```

Or run the API locally (Qdrant and any other required services must be available):

```bash
./run.sh --normal
```

Locally, the API listens on port `4004` by default. Docker Compose publishes it
on port `8004` by default; set `HOST_HTTP_PORT` to change that host port.
`./run.sh --help` lists all available options. Add `--index` to either command
to index the knowledge documents as part of startup:

```bash
./run.sh --index
./run.sh --normal --index
```

The equivalent Compose command is:

```bash
docker compose up --build
```

## Index knowledge documents

Indexing requires a working Qdrant connection and an embedding provider configured
in `.env`. The `--index` option runs the indexer as part of startup. To run it
manually:

```bash
# Local service environment
source .venv/bin/activate
python -m app.rag.indexer

# Docker Compose
docker compose exec dragbizz-ai python -m app.rag.indexer --yes
```

## Endpoints

| Endpoint | Access |
|---|---|
| `http://localhost:4004` (local) / `http://localhost:8004` (Docker) | API |
| `/docs` | Swagger UI |
| `/api/v1/health` | Public health check |
| `/api/v1/ready` | Public readiness check |
| `POST /api/v1/chat` | Bearer token or `at` cookie required |

## Chat request example

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
