#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "backend/.venv not found."
  echo "Run: bash scripts/setup_backend.sh"
  exit 1
fi

cd "$BACKEND_DIR"
"$VENV_DIR/bin/pip" install -r requirements_min.txt
"$VENV_DIR/bin/pip" install -r requirements_visual_extra.txt

cat <<'EOF'

Backend full visual setup complete.

Next:
  1. Verify ffmpeg is installed
  2. Run:
     bash scripts/dev_backend.sh

EOF
