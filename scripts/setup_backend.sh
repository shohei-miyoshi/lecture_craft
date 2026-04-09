#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"

cd "$BACKEND_DIR"

choose_python() {
  if command -v python3.10 >/dev/null 2>&1; then
    echo "python3.10"
    return
  fi
  if command -v python3.11 >/dev/null 2>&1; then
    echo "python3.11"
    return
  fi
  echo "python3"
}

PYTHON_BIN="$(choose_python)"

if [ -d "$VENV_DIR" ] && [ -x "$VENV_DIR/bin/python" ]; then
  VENV_MM="$("$VENV_DIR/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  case "$VENV_MM" in
    3.10|3.11)
      ;;
    *)
      echo "Existing backend/.venv uses Python $VENV_MM, which is not supported for this project."
      echo "Please run:"
      echo "  rm -rf $VENV_DIR"
      echo "  bash scripts/setup_backend.sh"
      exit 1
      ;;
  esac
fi

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install -r requirements_min.txt

cat <<'EOF'

Backend setup complete.

Next:
  1. Put your key in ~/.config/lecture_craft/apikey.txt
     or export OPENAI_API_KEY
  2. Run:
     bash scripts/dev_backend.sh

If you want video / video_highlight mode in backend/.venv:
  bash scripts/setup_backend_full.sh

EOF
