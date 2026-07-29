#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
BACKEND_VENV="$BACKEND_DIR/.venv/bin/python"
LEGACY_VENV="$ROOT_DIR/../auto_lecture/.venv/bin/python"

python_has_modules() {
  local py_bin="$1"
  local modules_csv="$2"
  "$py_bin" - "$modules_csv" <<'PY' >/dev/null 2>&1
import importlib.util
import sys

mods = [m for m in sys.argv[1].split(",") if m]
missing = [m for m in mods if importlib.util.find_spec(m) is None]
sys.exit(1 if missing else 0)
PY
}

FULL_STACK_MODULES="fastapi,uvicorn,moviepy,detectron2,imageio_ffmpeg"
API_ONLY_MODULES="fastapi,uvicorn"

if [ -x "$BACKEND_VENV" ] && python_has_modules "$BACKEND_VENV" "$FULL_STACK_MODULES"; then
  PYTHON_BIN="$BACKEND_VENV"
elif [ -x "$LEGACY_VENV" ] && python_has_modules "$LEGACY_VENV" "$FULL_STACK_MODULES"; then
  PYTHON_BIN="$LEGACY_VENV"
  echo "Using ../auto_lecture/.venv because it already includes the visual pipeline dependencies."
elif [ -x "$BACKEND_VENV" ] && python_has_modules "$BACKEND_VENV" "$API_ONLY_MODULES"; then
  PYTHON_BIN="$BACKEND_VENV"
  echo "Starting with backend/.venv, but video and video_highlight mode may fail because visual deps are missing."
  echo "Run: bash scripts/setup_backend_full.sh"
elif [ -x "$LEGACY_VENV" ] && python_has_modules "$LEGACY_VENV" "$API_ONLY_MODULES"; then
  PYTHON_BIN="$LEGACY_VENV"
  echo "Using ../auto_lecture/.venv with API-only dependencies."
  echo "Video and video_highlight mode may fail because visual deps are missing."
else
  echo "Python venv not found."
  echo "Run: bash scripts/setup_backend.sh"
  exit 1
fi

cd "$BACKEND_DIR"
exec "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
