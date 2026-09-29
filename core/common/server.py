from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


def run_server(name: str, host: str, port: int, routes: dict[str, Callable[[], tuple[int, dict]]]) -> None:
    class Handler(BaseHTTPRequestHandler):
        server_version = "TooruDragon/0.1.0-alpha"

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            route = self.path.split("?", 1)[0]
            if route == "/":
                self._send_json(200, {
                    "service": name,
                    "version": "0.1.0-alpha",
                    "status": "running",
                })
                return

            handler = routes.get(route)
            if handler is None:
                self._send_json(404, {
                    "error": "not_found",
                    "path": route,
                })
                return

            try:
                status, payload = handler()
                self._send_json(status, payload)
            except Exception as exc:
                self._send_json(500, {
                    "service": name,
                    "status": "error",
                    "error": str(exc),
                })

        def log_message(self, fmt: str, *args) -> None:
            print(f"[{name}] {self.address_string()} - {fmt % args}")

    print(f"[{name}] listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
