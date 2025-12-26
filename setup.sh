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
