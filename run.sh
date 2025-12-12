#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# Activate local venv if present (not required for Docker, but harmless).
if [ -f "env/bin/activate" ]; then
  # shellcheck disable=SC1090
  source "env/bin/activate"
fi
pip install -r requirements.txt

# Ensure compose is fresh
docker compose down --remove-orphans

# Start all services; api is overridden to run with --reload
docker compose up --build --force-recreate --remove-orphans -d

# Show status; containers stay up even if the terminal closes.
docker compose ps

