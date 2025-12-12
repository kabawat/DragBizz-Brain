#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# Ensure compose is fresh
docker compose down --remove-orphans

# Start all services; api is overridden to run with --reload
docker compose up --build --force-recreate --remove-orphans -d

# Show status; containers stay up even if the terminal closes.
docker compose ps

