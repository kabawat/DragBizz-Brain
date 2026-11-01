# Usage: source ./init.sh
# Activates the dragbizz-ai virtualenv in the current shell.

_INIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "Run this with: source ./init.sh"
  exit 1
fi

if [ ! -f "$_INIT_DIR/.venv/bin/activate" ]; then
  echo "Virtual environment not found. Run ./setup.sh first."
  return 1
fi

source "$_INIT_DIR/.venv/bin/activate"
echo "venv active: $(python --version) @ $_INIT_DIR/.venv"
