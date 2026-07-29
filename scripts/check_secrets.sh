#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:-}"
if [ -n "$MODE" ] && [ "$MODE" != "--staged" ] && [ "$MODE" != "--tracked" ]; then
  echo "Usage: bash scripts/check_secrets.sh [--staged|--tracked]" >&2
  exit 2
fi

if [ "$MODE" = "--staged" ]; then
  STAGED_ONLY=1
else
  STAGED_ONLY=0
fi

BLOCKED_FILES="$(mktemp)"
CLIENT_ENV_HITS="$(mktemp)"
OPENAI_KEY_HITS="$(mktemp)"
trap 'rm -f "$BLOCKED_FILES" "$CLIENT_ENV_HITS" "$OPENAI_KEY_HITS"' EXIT

list_files() {
  if [ "$STAGED_ONLY" -eq 1 ]; then
    git diff --cached --name-only --diff-filter=ACMR
  else
    git ls-files
  fi
}

read_file_content() {
  local file="$1"
  if [ "$STAGED_ONLY" -eq 1 ]; then
    git show ":$file" 2>/dev/null || true
  elif [ -f "$file" ]; then
    cat "$file"
  fi
}

while IFS= read -r file; do
  [ -n "$file" ] || continue

  case "$file" in
    .env|.env.*|*/.env|*/.env.*)
      case "$file" in
        .env.example|.env.sample|.env.template|*/.env.example|*/.env.sample|*/.env.template)
          ;;
        *)
          printf '%s\n' "$file" >> "$BLOCKED_FILES"
          ;;
      esac
      ;;
  esac

  case "$file" in
    apikey.txt|*/apikey.txt|openai_api_key|*/openai_api_key|openai_api_key.txt|*/openai_api_key.txt|secret.txt|*/secret.txt|*.secret)
      printf '%s\n' "$file" >> "$BLOCKED_FILES"
      ;;
  esac

  content="$(read_file_content "$file")"
  [ -n "$content" ] || continue

  if printf '%s\n' "$content" | grep -Eiq '^[[:space:]]*VITE_[A-Z0-9_]*(OPENAI|ANTHROPIC|GEMINI|CLAUDE|DEEPSEEK|API_KEY|SECRET|PASSWORD|PRIVATE)[A-Z0-9_]*[[:space:]]*='; then
    printf '%s\n' "$file" >> "$CLIENT_ENV_HITS"
  fi

  if printf '%s\n' "$content" | grep -Eq 'sk-(proj-)?[A-Za-z0-9_-]{20,}'; then
    printf '%s\n' "$file" >> "$OPENAI_KEY_HITS"
  fi
done <<EOF
$(list_files)
EOF

if [ ! -s "$BLOCKED_FILES" ] && [ ! -s "$CLIENT_ENV_HITS" ] && [ ! -s "$OPENAI_KEY_HITS" ]; then
  echo "Secret safety check passed."
  exit 0
fi

echo "Secret safety check failed." >&2

if [ -s "$BLOCKED_FILES" ]; then
  echo >&2
  echo "Do not commit local env or key files:" >&2
  sort -u "$BLOCKED_FILES" | sed 's/^/  - /' >&2
fi

if [ -s "$CLIENT_ENV_HITS" ]; then
  echo >&2
  echo "Secret-like VITE_* variables were found. VITE_* values are public in the browser:" >&2
  sort -u "$CLIENT_ENV_HITS" | sed 's/^/  - /' >&2
fi

if [ -s "$OPENAI_KEY_HITS" ]; then
  echo >&2
  echo "Text that looks like an OpenAI API key was found:" >&2
  sort -u "$OPENAI_KEY_HITS" | sed 's/^/  - /' >&2
fi

echo >&2
echo "Use backend environment variables or ~/.config/lecture_craft/ for local keys." >&2
exit 1
