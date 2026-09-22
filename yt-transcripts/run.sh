#!/usr/bin/env bash
# One-command start: checks Python, creates a virtualenv, upgrades deps, launches the UI.
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install it from https://www.python.org/downloads/ or 'brew install python'."
  exit 1
fi

# Require Python 3.10+ (youtube-transcript-api 1.x + modern yt-dlp).
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Python 3.10 or newer is required (you have $(python3 -V 2>&1))."
  echo "Install a newer Python (e.g. 'brew install python@3.12') and run this again."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating virtual environment…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "Upgrading dependencies (yt-dlp + youtube-transcript-api)…"
pip install -q --upgrade pip
pip install -q --upgrade -r requirements.txt

echo "Starting… your browser will open at http://127.0.0.1:${PORT:-7654}"
exec python app.py
