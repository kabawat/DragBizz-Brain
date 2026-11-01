# DragBizz Brain setup

## Step: 1 — Requirements

Requires Docker Compose and Yarn. Local Python development requires Python 3.11+.

## Step: 2 — Start dependencies

Start [Infra](../DragBizz-Infra/SETUP.MD) and [Core](../DragBizz-Core/SETUP.MD).

## Step: 3 — Configure the env file

Copy `env.example` to `.env`. Configure AI provider credentials, API URLs and `AI_REDIS_URL` from Infra's `redis/secrets/brain.env`.

## Step: 4 — Start development

Provision Brain's TLS certificates at the paths declared in Compose, then start:

```bash
yarn dev:start
yarn dev:logs
```

## Step: 5 — Index knowledge

Index knowledge after configuring the embedding provider:

```bash
docker compose -f docker-compose.dev.yml exec dragbizz-ai python -m app.rag.indexer --yes
```

For production, create `.env.production` from `env.example`, use production Redis credentials and provision certificates under `/etc/dragbizz/production/pki/brain/`. Start production Core first, then run `yarn prod:start`.

Stop with `yarn dev:stop` or `yarn prod:stop`. For local Python development, use `bash setup.sh` followed by `bash run.sh --normal` with reachable dependencies.
