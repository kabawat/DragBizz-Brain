# DragBizz AI Service

Provider-independent FastAPI foundation for DragBizz AI orchestration.

## Current scope

Implemented:

- FastAPI application factory and lifespan management
- Versioned health and readiness endpoints
- Request ID propagation
- Structured JSON logging and consistent error responses
- Provider interface and model router
- Allowlisted tool registry with risk classification
- Docker runtime and unit tests

Not implemented yet:

- JWT/JWKS authentication
- OpenAI, Claude, Gemini, DeepSeek, or local model adapters
- `/chat`, `/voice`, `/image`, or `/document` APIs
- Conversation persistence, Redis, queues, STT, TTS, or business tools

The service does not access DragBizz databases directly. Future tools must call
approved business-service APIs with caller identity and store scope preserved.

## Local setup

```bash
./setup.sh
./run.sh
```

Service endpoints:

- API: `http://localhost:4004`
- Swagger: `http://localhost:4004/docs`
- Health: `http://localhost:4004/api/v1/health`
- Readiness: `http://localhost:4004/api/v1/ready`

## Tests and lint

```bash
source .venv/bin/activate
pytest
ruff check .
```

## Docker

```bash
docker compose up --build
```

Docker exposes the service on `http://localhost:3000`.

## Configuration

Copy `.env.example` to `.env`. All service settings use the `AI_` prefix.
Provider secrets are intentionally absent until their adapters are implemented.

## Extension flow

1. Implement a `ModelProvider` adapter in `app/providers/`.
2. Register and activate it through `ModelRouter`.
3. Add authenticated API routes only after JWKS verification exists.
4. Register approved business tools through `ToolRegistry`.
5. Require validation, permissions, idempotency, and confirmation according to
   each tool's risk.
