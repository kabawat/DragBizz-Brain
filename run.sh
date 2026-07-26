#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

MODE=docker
DO_INDEX=0
PASS_ARGS=()

for arg in "$@"; do
  case "$arg" in
    --normal)
      MODE=normal
      ;;
    --index)
      DO_INDEX=1
      ;;
    -h|--help)
      cat <<'EOF'
Usage: ./run.sh [--normal] [--index] [extra args...]

  (default)     Start with Docker Compose (qdrant + AI)
  --normal      Start locally via .venv + uvicorn --reload
  --index       Index knowledge/ into Qdrant before/after start
  -h, --help    Show this help

Examples:
  ./run.sh
  ./run.sh --index
  ./run.sh --normal
  ./run.sh --normal --index
EOF
      exit 0
      ;;
    *)
      PASS_ARGS+=("$arg")
      ;;
  esac
done

run_index_local() {
  echo "Indexing knowledge/ into Qdrant (local)..."
  INDEX_ARGS=()
  if [ "${AI_ENVIRONMENT:-}" = "production" ]; then
    INDEX_ARGS+=(--yes)
  fi
  python -m app.rag.indexer "${INDEX_ARGS[@]}"
}

run_index_docker() {
  echo "Indexing knowledge/ into Qdrant (docker)..."
  docker compose exec -T dragbizz-ai python -m app.rag.indexer --yes
}

if [ "$MODE" = "normal" ]; then
  if [ ! -x ".venv/bin/python" ]; then
    echo "Virtual environment not found. Run ./setup.sh first."
    exit 1
  fi
  # shellcheck source=/dev/null
  source .venv/bin/activate

  if [ "$DO_INDEX" -eq 1 ]; then
    run_index_local
  fi

  exec python -m uvicorn app.main:app \
    --reload \
    --host "${AI_HOST:-0.0.0.0}" \
    --port "${AI_PORT:-4004}" \
    "${PASS_ARGS[@]}"
fi

# --- Docker (default) ---
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not found. Install Docker, or use ./run.sh --normal"
  exit 1
fi

if [ "$DO_INDEX" -eq 1 ]; then
  docker compose up --build -d "${PASS_ARGS[@]}"
  echo "Waiting for dragbizz-ai..."
  for _ in $(seq 1 60); do
    if docker compose exec -T dragbizz-ai \
      python -c "import urllib.request; urllib.request.urlopen('http://localhost:4004/api/v1/health')" \
      >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  run_index_docker
  exec docker compose logs -f --tail=100
fi

exec docker compose up --build "${PASS_ARGS[@]}"
