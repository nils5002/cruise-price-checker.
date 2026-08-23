#!/bin/sh
# Prepare the data volume and drop privileges before starting the app.
set -e

DATA_DIR="${DATA_DIR:-/data}"
mkdir -p "$DATA_DIR/screenshots" "$DATA_DIR/snapshots" "$DATA_DIR/browser-profiles"

if [ "$(id -u)" = "0" ]; then
    chown -R pwuser:pwuser "$DATA_DIR" 2>/dev/null || true
    if command -v setpriv >/dev/null 2>&1; then
        exec setpriv --reuid=pwuser --regid=pwuser --init-groups "$@"
    fi
fi

exec "$@"
