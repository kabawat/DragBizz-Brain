#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# Tail API logs; adjust service name to view other services (mongo/redis).
docker compose logs -f api

