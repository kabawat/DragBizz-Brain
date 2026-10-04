#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  cat <<'EOF'
Usage: ./logs.sh [service...]

Follow Docker Compose logs (last 100 lines, then new output).

Examples:
  ./logs.sh
  ./logs.sh dragbizz-ai
  ./logs.sh qdrant
EOF
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not found."
  exit 1
fi

exec docker compose logs -f --tail=100 "$@"
