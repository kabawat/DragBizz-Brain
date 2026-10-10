#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -e ".venv" ] && { [ ! -f ".venv/bin/activate" ] || [ ! -x ".venv/bin/python" ]; }; then
  backup=".venv.incomplete.$(date +%Y%m%d%H%M%S).$$"
  mv ".venv" "$backup"
  echo "Incomplete virtual environment moved to $backup."
fi

if [ ! -f ".venv/bin/activate" ] || [ ! -x ".venv/bin/python" ]; then
  if venv_output=$(python3 -m venv .venv 2>&1); then
    :
  else
    printf '%s\n' "$venv_output" >&2
    if [[ "$venv_output" != *"ensurepip is not available"* ]]; then
      exit 1
    fi

    if [[ ! -f /etc/os-release ]] || ! grep -Eq '^(ID=debian|ID=ubuntu|ID_LIKE=.*debian)' /etc/os-release || ! command -v apt-get >/dev/null 2>&1; then
      echo "ERROR: python3-venv is missing. Install the venv package for your Python version, then rerun ./setup.sh." >&2
      exit 1
    fi

    python_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    venv_package="python${python_version}-venv"
    if [[ "$EUID" -eq 0 ]]; then
      APT_GET=(apt-get)
    elif command -v sudo >/dev/null 2>&1; then
      APT_GET=(sudo apt-get)
    else
      echo "ERROR: Install $venv_package with root privileges, then rerun ./setup.sh." >&2
      exit 1
    fi

    echo "Installing the missing $venv_package system package..."
    "${APT_GET[@]}" update
    "${APT_GET[@]}" install -y "$venv_package"
    python3 -m venv .venv
  fi
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

echo "Setup complete. Run ./run.sh (Docker) or ./run.sh --normal (local)."
