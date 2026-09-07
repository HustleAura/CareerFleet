#!/usr/bin/env bash
# Entry point for transcription: runs transcribe.py inside the project venv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$REPO_ROOT/.venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Virtualenv missing at $REPO_ROOT/.venv" >&2
  echo "Create it with:" >&2
  echo "  /opt/homebrew/bin/python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

exec "$VENV_PYTHON" "$REPO_ROOT/scripts/transcribe.py" "$@"
