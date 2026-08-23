#!/usr/bin/env bash
# Lokaler Test ohne Docker: Backend (SQLite) + gebautes Frontend.
# Start:  ./scripts/local-start.sh     Stop:  ./scripts/local-stop.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WEB_PORT="${WEB_PORT:-8080}"
API_PORT="${API_PORT:-8000}"
RUN_DIR="$ROOT/backend/data/local"
VENV="$ROOT/backend/.venv"

mkdir -p "$RUN_DIR"

if [ ! -x "$VENV/bin/python" ]; then
    echo "==> Virtuelle Umgebung anlegen"
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --upgrade pip >/dev/null
    # psycopg2 wird lokal nicht gebraucht (SQLite) und hat auf manchen Macs kein Wheel
    grep -v psycopg2 backend/requirements.txt > "$RUN_DIR/req.txt"
    "$VENV/bin/pip" install -r "$RUN_DIR/req.txt"
    "$VENV/bin/playwright" install chromium
fi

if [ ! -d "$ROOT/frontend/dist" ]; then
    echo "!! frontend/dist fehlt. Einmalig bauen:  cd frontend && npm ci && npx vite build"
    exit 1
fi

echo "==> Backend starten (Port $API_PORT, SQLite)"
cd "$ROOT/backend"
DATA_DIR="./data/local" \
DATABASE_URL="sqlite:///./data/local/app.db" \
ENV_FILE="./nonexistent.env" \
ENABLE_FIREFOX="false" \
HEADLESS="${HEADLESS:-true}" \
ENABLE_SCHEDULER="true" \
DELAY_BETWEEN_PROFILES_S="${DELAY_BETWEEN_PROFILES_S:-2}" \
LOG_LEVEL="INFO" \
nohup "$VENV/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$API_PORT" \
    > "$RUN_DIR/backend.log" 2>&1 &
echo $! > "$RUN_DIR/backend.pid"

cd "$ROOT"
for _ in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1; then break; fi
    sleep 1
done

echo "==> Frontend ausliefern (Port $WEB_PORT)"
nohup "$VENV/bin/python" scripts/serve_frontend.py "frontend/dist" "$WEB_PORT" \
    "http://127.0.0.1:$API_PORT" > "$RUN_DIR/frontend.log" 2>&1 &
echo $! > "$RUN_DIR/frontend.pid"
sleep 1

echo
if curl -sf "http://127.0.0.1:$WEB_PORT/health" >/dev/null 2>&1; then
    echo "Läuft:  http://localhost:$WEB_PORT"
    echo "API:    http://localhost:$WEB_PORT/api/meta"
    echo "Docs:   http://localhost:$WEB_PORT/docs"
    echo "Logs:   $RUN_DIR/backend.log"
    echo "Stop:   ./scripts/local-stop.sh"
else
    echo "Start fehlgeschlagen - Log:"
    tail -20 "$RUN_DIR/backend.log"
    exit 1
fi
