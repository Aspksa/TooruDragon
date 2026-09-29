from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.system.config import cores_config, system_config
from core.system.core_manager import CoreManager
from core.system.database import Database
from core.system.logging import get_logger

logger = get_logger("supervisor")
config = system_config()
cores_cfg = cores_config()
host = cores_cfg.get("host", "127.0.0.1")
cores = dict(cores_cfg.get("cores", {}))
supervisor_cfg = config.get("supervisor", {})
listen_host = str(supervisor_cfg.get("host", "127.0.0.1"))
listen_port = int(supervisor_cfg.get("port", 8699))
interval = max(2, int(supervisor_cfg.get("interval_seconds", 5)))
failure_threshold = max(1, int(supervisor_cfg.get("failure_threshold", 3)))
safe_mode_file = ROOT / "runtime" / "safe_mode.json"

manager = CoreManager(host=host, cores=cores, root=ROOT)
db = Database()
failures = {name: 0 for name in cores}
started = time.monotonic()


def safe_mode() -> bool:
    return safe_mode_file.exists()


def set_safe_mode(enabled: bool, reason: str = "") -> None:
    safe_mode_file.parent.mkdir(parents=True, exist_ok=True)
    if enabled:
        safe_mode_file.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "reason": reason,
                    "created_at": time.time(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    else:
        safe_mode_file.unlink(missing_ok=True)


def snapshot() -> dict:
    return {
        "service": "supervisor",
        "status": "ok",
        "uptime_seconds": int(time.monotonic() - started),
        "safe_mode": safe_mode(),
        "cores": manager.snapshot(),
    }


def recovery_loop() -> None:
    while True:
        if safe_mode():
            time.sleep(interval)
            continue

        for name in cores:
            if name == "main":
                continue
            status = manager.status(name)
            if status.get("online"):
                failures[name] = 0
                continue

            failures[name] += 1
            logger.warning(
                "Supervisor health failure %s: %s/%s",
                name,
                failures[name],
                failure_threshold,
            )
            if failures[name] >= failure_threshold:
                result = manager.restart(name)
                logger.warning("Supervisor recovery %s: %s", name, result)
                failures[name] = 0

        time.sleep(interval)


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, {
                "service": "supervisor",
                "status": "ok",
                "safe_mode": safe_mode(),
            })
            return
        if self.path == "/status":
            self.send_json(200, snapshot())
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path == "/safe-mode/enable":
            set_safe_mode(True, "api_request")
            self.send_json(200, {"safe_mode": True})
            return
        if self.path == "/safe-mode/disable":
            set_safe_mode(False)
            self.send_json(200, {"safe_mode": False})
            return
        self.send_json(404, {"error": "not_found"})

    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)


def main() -> int:
    db.initialize(str(config.get("version", "0.3.0-alpha")))
    thread = threading.Thread(
        target=recovery_loop,
        name="toorudragon-supervisor-recovery",
        daemon=True,
    )
    thread.start()
    logger.info(
        "External Supervisor listening on http://%s:%s",
        listen_host,
        listen_port,
    )
    ThreadingHTTPServer((listen_host, listen_port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
