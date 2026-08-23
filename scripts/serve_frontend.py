#!/usr/bin/env python3
"""Kleiner Entwicklungsserver fuer den lokalen Test ohne Docker.

Liefert das gebaute Frontend (``frontend/dist``) aus und leitet ``/api``,
``/health``, ``/docs`` und ``/openapi.json`` an das Backend weiter -- also
genau das, was im Betrieb der nginx-Container macht.

Nur fuer lokale Tests gedacht: keine Zugriffsbeschraenkung, single-threaded
ThreadingHTTPServer, kein TLS.
"""
from __future__ import annotations

import http.server
import os
import socketserver
import sys
import urllib.error
import urllib.request

PROXY_PREFIXES = ("/api/", "/health", "/docs", "/openapi.json", "/redoc")
FORWARD_HEADERS = ("Content-Type", "Accept", "X-API-Key")


class Handler(http.server.SimpleHTTPRequestHandler):
    root_dir = "."
    backend = "http://127.0.0.1:8000"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=self.root_dir, **kwargs)

    # -- proxy ---------------------------------------------------------
    def _proxy(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        request = urllib.request.Request(self.backend + self.path, data=body, method=method)
        for header in FORWARD_HEADERS:
            if self.headers.get(header):
                request.add_header(header, self.headers[header])
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in ("transfer-encoding", "connection", "content-length"):
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        except urllib.error.HTTPError as error:
            payload = error.read()
            self.send_response(error.code)
            self.send_header("Content-Type", error.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:  # noqa: BLE001
            message = f'{{"detail":"Backend nicht erreichbar: {type(exc).__name__}"}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

    # -- static + SPA fallback ----------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith(PROXY_PREFIXES):
            return self._proxy("GET")
        target = self.translate_path(self.path)
        if not os.path.exists(target) and "." not in os.path.basename(self.path):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        return self._proxy("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        return self._proxy("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        return self._proxy("DELETE")

    def end_headers(self) -> None:
        if self.path.endswith((".html", "/")) or self.path == "/index.html":
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args) -> None:  # noqa: A002
        pass


def main() -> int:
    Handler.root_dir = sys.argv[1] if len(sys.argv) > 1 else "frontend/dist"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    Handler.backend = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8000"
    if not os.path.isdir(Handler.root_dir):
        print(f"Frontend-Build fehlt: {Handler.root_dir} (vorher 'npm ci && npx vite build')")
        return 1
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", port), Handler) as httpd:
        print(f"Oberflaeche: http://localhost:{port}  (API-Proxy -> {Handler.backend})", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("beendet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
