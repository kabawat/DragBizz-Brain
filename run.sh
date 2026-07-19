#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Virtual environment not found. Run ./setup.sh first."
  exit 1
fi

source .venv/bin/activate
exec python -m uvicorn app.main:app \
  --reload \
  --host "${AI_HOST:-0.0.0.0}" \
  --port "${AI_PORT:-4004}"
