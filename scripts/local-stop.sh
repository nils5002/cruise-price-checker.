#!/usr/bin/env bash
# Beendet die lokal gestarteten Prozesse.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT/backend/data/local"

for name in frontend backend; do
    pid_file="$RUN_DIR/$name.pid"
    if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
        kill "$(cat "$pid_file")" && echo "$name gestoppt (PID $(cat "$pid_file"))"
    else
        echo "$name lief nicht"
    fi
    rm -f "$pid_file"
done
