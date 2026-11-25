#!/usr/bin/env bash
# Starts FastAPI (:8000) and Vite (:5173). Works on Linux/macOS and Git Bash on Windows.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# --- backend venv
if [ -x backend/.venv/Scripts/python.exe ]; then PY="backend/.venv/Scripts/python.exe"
elif [ -x backend/.venv/bin/python ]; then PY="backend/.venv/bin/python"
else
  echo "› Creating backend virtualenv…"
  if command -v py >/dev/null 2>&1; then py -3.12 -m venv backend/.venv 2>/dev/null || py -3 -m venv backend/.venv
  else python3 -m venv backend/.venv; fi
  if [ -x backend/.venv/Scripts/python.exe ]; then PY="backend/.venv/Scripts/python.exe"; else PY="backend/.venv/bin/python"; fi
  "$PY" -m pip install -q -r backend/requirements.txt
fi

# --- frontend deps
if [ ! -d frontend/node_modules ]; then
  echo "› Installing frontend dependencies…"
  (cd frontend && npm install --no-audit --no-fund)
fi

pids=()
cleanup() { echo; echo "Shutting down…"; for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

echo "› API      → http://localhost:8000  (docs: /docs)"
(cd backend && "../$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) &
pids+=($!)

echo "› Frontend → http://localhost:5173"
(cd frontend && npm run dev -- --host 127.0.0.1) &
pids+=($!)

wait -n
