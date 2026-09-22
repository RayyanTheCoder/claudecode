#!/usr/bin/env bash
# One-command start: creates a virtualenv, installs deps, launches the web UI.
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install it from https://www.python.org/downloads/ or 'brew install python'."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating virtual environment…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "Installing dependencies…"
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "Starting… your browser will open at http://127.0.0.1:${PORT:-7654}"
exec python app.py
