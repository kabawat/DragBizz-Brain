#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-env}"

echo "Using python: $PYTHON_BIN"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Error: $PYTHON_BIN not found. Please install Python 3." >&2
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment at $PROJECT_ROOT/$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  echo "Virtual environment already exists at $PROJECT_ROOT/$VENV_DIR"
fi

echo "Activating virtual environment"
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

echo "Upgrading pip"
pip install --upgrade pip

echo "Installing Python dependencies"
pip install -r requirements.txt

echo "Setting up application directories"
mkdir -p app/data
mkdir -p logs

echo "Initializing AI models file if not exists"
MODELS_FILE="app/data/available_models.json"
if [ ! -f "$MODELS_FILE" ]; then
  echo "Creating default models file..."
  cat > "$MODELS_FILE" << 'EOF'
[
  "xiaomi/mimo-v2-flash:free",
  "nvidia/nemotron-3-nano-30b-a3b:free",
  "mistralai/devstral-2512:free",
  "arcee-ai/trinity-mini:free",
  "tngtech/tng-r1t-chimera:free",
  "nvidia/nemotron-nano-12b-v2-vl:free",
  "openai/gpt-oss-120b:free",
  "z-ai/glm-4.5-air:free",
  "qwen/qwen3-coder:free",
  "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
  "tngtech/deepseek-r1t2-chimera:free",
  "deepseek/deepseek-r1-0528:free",
  "tngtech/deepseek-r1t-chimera:free",
  "google/gemma-3-27b-it:free",
  "google/gemini-2.0-flash-exp:free",
  "meta-llama/llama-3.3-70b-instruct:free",
  "qwen/qwen3-4b:free",
  "google/gemma-3n-e4b-it:free",
  "moonshotai/kimi-k2:free",
  "openai/gpt-oss-20b:free",
  "nvidia/nemotron-nano-9b-v2:free",
  "arcee-ai/trinity-mini:free",
  "allenai/molmo-2-8b:free"
]
EOF
  echo "Models file created at $MODELS_FILE"
else
  echo "Models file already exists at $MODELS_FILE"
fi

echo "Initializing vision models file if not exists"
VISION_MODELS_FILE="app/data/vision_models.json"
if [ ! -f "$VISION_MODELS_FILE" ]; then
  echo "Creating default vision models file..."
  cat > "$VISION_MODELS_FILE" << 'EOF'
[
  "allenai/molmo-2-8b:free",
  "nvidia/nemotron-nano-12b-v2-vl:free",
  "mistralai/mistral-small-3.1-24b-instruct:free",
  "google/gemma-3-4b-it:free",
  "google/gemma-3-12b-it:free",
  "google/gemma-3-27b-it:free",
  "google/gemini-2.0-flash-exp:free",
  "qwen/qwen-2.5-vl-7b-instruct:free"
]
EOF
  echo "Vision models file created at $VISION_MODELS_FILE"
else
  echo "Vision models file already exists at $VISION_MODELS_FILE"
fi

echo "Checking for .env file"
if [ ! -f ".env" ]; then
  echo "Warning: .env file not found. Please create one with required environment variables."
  echo "Required variables:"
  echo "  - OPENROUTER_API_KEY"
  echo "  - REDIS_HOST (default: localhost)"
  echo "  - REDIS_PORT (default: 6379)"
  echo "  - JWT_ALGORITHM (default: RS256)"
  echo "  - BASE_URL"
else
  echo ".env file found"
fi

echo ""
echo "Setup completed successfully!"
echo ""
echo "Next steps:"
echo "  1. Ensure .env file is configured with required variables"
echo "  2. Start Redis server (if not using Docker)"
echo "  3. Run the application:"
echo "     - Development: uvicorn app.main:app --reload"
echo "     - Production: gunicorn app.main:app -c gunicorn_config.py"
echo "     - Docker: docker compose up"
