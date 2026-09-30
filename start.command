#!/bin/bash
# macOS: double-click this file (first time: right-click → Open). Linux: run ./start.command
cd "$(dirname "$0")" || exit 1
PY=python3
command -v $PY >/dev/null 2>&1 || { echo "Python 3 not found. Install it from https://www.python.org/downloads/ and try again."; read -r -p "Press Enter to close"; exit 1; }
if [ ! -d .venv ]; then
  echo "First run: creating a private Python environment (one-time, ~1 minute)..."
  $PY -m venv .venv || exit 1
  .venv/bin/pip install --upgrade pip >/dev/null
  .venv/bin/pip install -r requirements.txt || { echo "Package install failed — see messages above."; read -r -p "Press Enter"; exit 1; }
fi
[ -f .env ] || cp .env.example .env
PORT=$(grep -E '^WFD_PORT=' .env | cut -d= -f2); PORT=${PORT:-8765}
( sleep 2; open "http://127.0.0.1:$PORT" 2>/dev/null || xdg-open "http://127.0.0.1:$PORT" 2>/dev/null ) &
.venv/bin/python -m app.server
