from __future__ import annotations

import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .auth import AuthService


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    json: dict | list | None
    request_id: str


@dataclass
class Route:
    handler: Callable[[Request], tuple[int, dict]]
    method: str = "GET"
    protected: bool = True


def run_server(
    name: str,
    host: str,
    port: int,
    version: str,
    routes: dict[str, Route],
    auth: AuthService,
    logger,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"TooruDragon/{version}"

        def _send_json(self, status: int, payload: dict, request_id: str | None = None) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Cache-Control", "no-store")
            if request_id:
                self.send_header("X-Request-Id", request_id)
            self.end_headers()
            self.wfile.write(body)

        def _request(self) -> Request:
            parsed = urlparse(self.path)
            payload = None
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length:
                raw = self.rfile.read(length)
                if raw:
                    payload = json.loads(raw.decode("utf-8"))
            request_id = self.headers.get("X-Request-Id") or str(uuid4())
            return Request(
                method=self.command,
                path=parsed.path,
                query=parse_qs(parsed.query),
                headers={key: value for key, value in self.headers.items()},
                json=payload,
                request_id=request_id,
            )

        def _dispatch(self) -> None:
            try:
                request = self._request()
                if request.path == "/":
                    self._send_json(200, {
                        "service": name,
                        "version": version,
                        "status": "running",
                        "request_id": request.request_id,
                    }, request.request_id)
                    return

                route = routes.get(request.path)
                if route is None or route.method.upper() != request.method:
                    self._send_json(404, {"error": "not_found", "path": request.path}, request.request_id)
                    return

                if route.protected and not auth.authorize(
                    self.headers.get("Authorization")
                ):
                    self._send_json(401, {"error": "unauthorized"}, request.request_id)
                    return

                status, payload = route.handler(request)
                if isinstance(payload, dict):
                    payload.setdefault("request_id", request.request_id)
                self._send_json(status, payload, request.request_id)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid_json"})
            except Exception:
                logger.exception("Unhandled API error")
                self._send_json(500, {
                    "service": name,
                    "status": "error",
                    "error": "internal_server_error",
                })

        def do_GET(self) -> None:
            self._dispatch()

        def do_POST(self) -> None:
            self._dispatch()

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

        def log_message(self, fmt: str, *args) -> None:
            logger.info("%s - %s", self.address_string(), fmt % args)

    logger.info("Listening on http://%s:%s", host, port)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
