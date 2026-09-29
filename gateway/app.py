from __future__ import annotations

import hmac
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.system.config import cores_config, system_config
from core.system.logging import get_logger

logger = get_logger("gateway")
system = system_config()
registry = cores_config()
gateway_cfg = system.get("gateway", {})
listen_host = str(gateway_cfg.get("host", "127.0.0.1"))
listen_port = int(gateway_cfg.get("port", 8698))
target_host = str(registry.get("host", "127.0.0.1"))
auth_cfg = system.get("auth", {})
auth_required = bool(auth_cfg.get("required", False))
auth_token = str(auth_cfg.get("token", ""))

_lock = threading.RLock()
_generation = 1
_routes = {
    name: {
        "host": target_host,
        "port": int(entry["port"] if isinstance(entry, dict) else entry),
        "slot": "canonical",
    }
    for name, entry in registry.get("cores", {}).items()
}


def snapshot() -> dict:
    with _lock:
        return {
            "generation": _generation,
            "routes": json.loads(json.dumps(_routes)),
        }


def promote(core: str, host: str, port: int, slot: str) -> dict:
    global _generation
    if core not in _routes:
        raise KeyError(core)
    if not (1 <= int(port) <= 65535):
        raise ValueError("port out of range")
    with _lock:
        previous = dict(_routes[core])
        _routes[core] = {
            "host": str(host),
            "port": int(port),
            "slot": str(slot or "candidate"),
        }
        _generation += 1
        return {
            "core": core,
            "previous": previous,
            "active": dict(_routes[core]),
            "generation": _generation,
        }


def route_for(core: str) -> dict:
    with _lock:
        route = _routes.get(core)
        if route is None:
            raise KeyError(core)
        return dict(route)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def authorized(self) -> bool:
        if not auth_required:
            return True
        if not auth_token:
            return False
        header = self.headers.get("Authorization", "")
        scheme, _, provided = header.partition(" ")
        return (
            scheme.lower() == "bearer"
            and bool(provided)
            and hmac.compare_digest(provided, auth_token)
        )

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Request-Id")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self) -> None:
        parsed = urlsplit(self.path)
        parts = parsed.path.split("/")
        if len(parts) < 4 or parts[1] != "core":
            self.send_json(404, {"error": "not_found"})
            return

        core = parts[2]
        try:
            route = route_for(core)
        except KeyError:
            self.send_json(404, {"error": "unknown_core", "core": core})
            return

        forwarded_path = "/" + "/".join(parts[3:])
        if parsed.query:
            forwarded_path += "?" + parsed.query

        target = f"http://{route['host']}:{route['port']}{forwarded_path}"
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else None

        headers = {}
        for key in ("Authorization", "Content-Type", "X-Request-Id"):
            value = self.headers.get(key)
            if value:
                headers[key] = value

        request = urllib.request.Request(
            target,
            data=body,
            method=self.command,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read()
                self.send_response(response.status)
                self.send_header(
                    "Content-Type",
                    response.headers.get("Content-Type", "application/json; charset=utf-8"),
                )
                self.send_header("Content-Length", str(len(data)))
                self.send_header("X-TooruDragon-Route", f"{core}:{route['slot']}")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Request-Id")
                request_id = response.headers.get("X-Request-Id")
                if request_id:
                    self.send_header("X-Request-Id", request_id)
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as exc:
            data = exc.read()
            self.send_response(exc.code)
            self.send_header(
                "Content-Type",
                exc.headers.get("Content-Type", "application/json; charset=utf-8"),
            )
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-TooruDragon-Route", f"{core}:{route['slot']}")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Request-Id")
            self.end_headers()
            self.wfile.write(data)
        except (urllib.error.URLError, TimeoutError) as exc:
            self.send_json(503, {
                "error": "upstream_unavailable",
                "core": core,
                "route": route,
                "message": str(exc),
            })

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, {
                "service": "gateway",
                "status": "ok",
                **snapshot(),
            })
            return
        if self.path == "/routes":
            if not self.authorized():
                self.send_json(401, {"error": "unauthorized"})
                return
            self.send_json(200, snapshot())
            return
        self._proxy()

    def do_POST(self) -> None:
        if self.path == "/routes/promote":
            if not self.authorized():
                self.send_json(401, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                result = promote(
                    str(payload.get("core", "")).strip(),
                    str(payload.get("host", target_host)).strip() or target_host,
                    int(payload.get("port")),
                    str(payload.get("slot", "candidate")).strip(),
                )
                self.send_json(200, result)
            except KeyError:
                self.send_json(404, {"error": "unknown_core"})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": "invalid_route", "message": str(exc)})
            return

        self._proxy()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Request-Id")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)


def main() -> int:
    logger.info("Gateway listening on http://%s:%s", listen_host, listen_port)
    ThreadingHTTPServer((listen_host, listen_port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
