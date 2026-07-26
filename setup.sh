#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

echo "Setup complete. Run ./run.sh (Docker) or ./run.sh --normal (local)."
