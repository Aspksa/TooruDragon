from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8710

UPSTREAMS = {
    "main": "http://127.0.0.1:8700",
    "supervisor": "http://127.0.0.1:8699",
    "gateway": "http://127.0.0.1:8698",
    "tooru_ai": "http://127.0.0.1:8698/core/tooru_ai",
}

GET_ALLOWLIST = {
    "main": (
        "/health",
        "/live",
        "/ready",
        "/cores",
        "/api/cores",
        "/api/core/history",
        "/platform",
        "/api/tasks",
        "/api/task/transitions",
        "/events",
        "/events/replay",
        "/events/consumers",
        "/observability",
        "/registry",
        "/watchdog",
        "/compatibility",
        "/agents/tools",
    ),
    "tooru_ai": (
        "/health",
        "/runtime",
        "/models",
        "/conversations",
        "/conversation",
        "/memory/search",
    ),
    "supervisor": (
        "/health",
        "/status",
        "/deployments",
    ),
    "gateway": (
        "/health",
        "/routes",
    ),
}

POST_ALLOWLIST = {
    "main": (
        "/api/core/action",
        "/api/task/create",
        "/api/task/claim",
        "/api/task/update",
        "/events/publish",
        "/events/ack",
        "/events/dlq",
        "/agents/plan",
        "/agents/tool/invoke",
    ),
    "tooru_ai": (
        "/chat",
        "/memory/remember",
    ),
    "supervisor": (
        "/core/action",
        "/safe-mode/enable",
        "/safe-mode/disable",
        "/deployment/promote",
        "/deployment/rollback",
        "/deployment/complete",
    ),
    "gateway": (
        "/routes/promote",
    ),
}


def _allowed(method: str, upstream: str, path: str) -> bool:
    table = GET_ALLOWLIST if method == "GET" else POST_ALLOWLIST
    prefixes = table.get(upstream, ())
    return any(path == prefix or path.startswith(prefix + "?") for prefix in prefixes)


def _token() -> str:
    return os.getenv("TOORUDRAGON_API_TOKEN", "")


def _upstream_json(path: str, timeout: float = 10.0) -> dict:
    headers = {"Accept": "application/json"}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        UPSTREAMS["main"] + path,
        method="GET",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class Handler(BaseHTTPRequestHandler):
    server_version = "TooruDragonWeb/0.3.0"

    def _trusted_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return origin in {
            "http://127.0.0.1:8710",
            "http://localhost:8710",
        }


    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        request_id: str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'",
        )
        if request_id:
            self.send_header("X-Request-Id", request_id)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _stream_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        last_event_id = self.headers.get("Last-Event-ID", "").strip()
        last_sequence = int(last_event_id) if last_event_id.isdigit() else 0
        if not last_sequence:
            try:
                initial = _upstream_json("/events?limit=1", timeout=3.0)
                items = initial.get("events", [])
                if items:
                    last_sequence = int(items[0].get("sequence", 0))
            except Exception:
                pass

        deadline = time.monotonic() + 55
        try:
            while time.monotonic() < deadline:
                try:
                    data = _upstream_json(
                        f"/events?limit=100&after_sequence={last_sequence}",
                        timeout=3.0,
                    )
                    events = list(reversed(data.get("events", [])))
                    for event in events:
                        sequence = int(event.get("sequence", 0))
                        if sequence <= last_sequence:
                            continue
                        payload = json.dumps(event, ensure_ascii=False)
                        self.wfile.write(
                            f"id: {sequence}\nevent: durable_event\ndata: {payload}\n\n".encode("utf-8")
                        )
                        self.wfile.flush()
                        last_sequence = sequence
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                except Exception as exc:
                    payload = json.dumps({"message": str(exc)}, ensure_ascii=False)
                    self.wfile.write(
                        f"event: stream_error\ndata: {payload}\n\n".encode("utf-8")
                    )
                    self.wfile.flush()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _serve_static(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/":
            path = "/index.html"

        relative = path.lstrip("/")
        target = (ROOT / relative).resolve()
        try:
            target.relative_to(ROOT.resolve())
        except ValueError:
            self._json(403, {"error": "forbidden"})
            return

        if not target.is_file():
            self._json(404, {"error": "not_found"})
            return

        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {
            "application/javascript",
            "application/json",
        }:
            content_type += "; charset=utf-8"

        self._send_bytes(200, target.read_bytes(), content_type)

    def _proxy(self, method: str) -> None:
        parsed = urlsplit(self.path)
        parts = parsed.path.split("/")
        if len(parts) < 4 or parts[1] != "api":
            self._json(404, {"error": "not_found"})
            return

        upstream = parts[2]
        if upstream not in UPSTREAMS:
            self._json(404, {"error": "unknown_upstream"})
            return

        forwarded = "/" + "/".join(parts[3:])
        if parsed.query:
            forwarded += "?" + parsed.query

        if not _allowed(method, upstream, forwarded):
            self._json(403, {
                "error": "route_not_allowed",
                "upstream": upstream,
                "path": forwarded,
            })
            return

        body = None
        if method == "POST":
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length else b"{}"

        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"

        token = _token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        request_id = self.headers.get("X-Request-Id")
        if request_id:
            headers["X-Request-Id"] = request_id

        request = urllib.request.Request(
            UPSTREAMS[upstream] + forwarded,
            data=body,
            method=method,
            headers=headers,
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read()
                self._send_bytes(
                    response.status,
                    data,
                    response.headers.get(
                        "Content-Type",
                        "application/json; charset=utf-8",
                    ),
                    request_id=response.headers.get("X-Request-Id"),
                )
        except urllib.error.HTTPError as exc:
            data = exc.read()
            self._send_bytes(
                exc.code,
                data,
                exc.headers.get(
                    "Content-Type",
                    "application/json; charset=utf-8",
                ),
                request_id=exc.headers.get("X-Request-Id"),
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            self._json(503, {
                "error": "upstream_unavailable",
                "upstream": upstream,
                "message": str(exc),
            })

    def do_GET(self) -> None:
        if self.path == "/stream/events":
            self._stream_events()
            return
        if self.path == "/health":
            self._json(200, {
                "service": "web",
                "version": "0.3.0",
                "status": "ok",
                "control_center": True,
            })
            return
        if self.path.startswith("/api/"):
            self._proxy("GET")
            return
        self._serve_static()

    def do_POST(self) -> None:
        if self.path.startswith("/api/"):
            if not self._trusted_origin():
                self._json(403, {"error": "untrusted_origin"})
                return
            content_type = self.headers.get("Content-Type", "")
            if not content_type.lower().startswith("application/json"):
                self._json(415, {"error": "application_json_required"})
                return
            self._proxy("POST")
            return
        self._json(404, {"error": "not_found"})

    def log_message(self, fmt: str, *args) -> None:
        print(f"[web] {self.address_string()} - {fmt % args}")


def main() -> int:
    os.chdir(ROOT)
    print(f"[web] TooruDragon Control Center v0.3.0 on http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
