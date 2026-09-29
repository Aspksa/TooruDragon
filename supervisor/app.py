from __future__ import annotations

import hmac
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.system.config import cores_config, system_config
from core.system.core_manager import CoreManager
from core.system.database import Database
from core.system.deployment import Candidate, DeploymentCoordinator
from core.system.logging import get_logger

logger = get_logger("supervisor")
config = system_config()
cores_cfg = cores_config()
host = cores_cfg.get("host", "127.0.0.1")
cores = dict(cores_cfg.get("cores", {}))
supervisor_cfg = config.get("supervisor", {})
gateway_cfg = config.get("gateway", {})
gateway_host = str(gateway_cfg.get("host", "127.0.0.1"))
gateway_port = int(gateway_cfg.get("port", 8698))
gateway_enabled = bool(gateway_cfg.get("enabled", False))
auth_cfg = config.get("auth", {})
auth_required = bool(auth_cfg.get("required", False))
auth_token = str(auth_cfg.get("token", ""))

listen_host = str(supervisor_cfg.get("host", "127.0.0.1"))
listen_port = int(supervisor_cfg.get("port", 8699))
interval = max(2, int(supervisor_cfg.get("interval_seconds", 5)))
failure_threshold = max(1, int(supervisor_cfg.get("failure_threshold", 3)))
startup_grace_seconds = max(0, int(supervisor_cfg.get("startup_grace_seconds", 15)))
crash_loop_window_seconds = max(30, int(supervisor_cfg.get("crash_loop_window_seconds", 300)))
max_restarts_in_window = max(1, int(supervisor_cfg.get("max_restarts_in_window", 5)))
safe_mode_file = ROOT / "runtime" / "safe_mode.json"

manager = CoreManager(host=host, cores=cores, root=ROOT)
deployer = DeploymentCoordinator(root=ROOT)
db = Database()
failures = {name: 0 for name in cores}
restart_history = {name: [] for name in cores}
failures["gateway"] = 0
restart_history["gateway"] = []
active_deployments: dict[str, dict] = {}
deployment_lock = threading.RLock()
started = time.monotonic()

def gateway_online() -> bool:
    if not gateway_enabled:
        return True
    try:
        with urllib.request.urlopen(
            f"http://{gateway_host}:{gateway_port}/health",
            timeout=1.5,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and payload.get("status") == "ok"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False


def start_gateway() -> dict:
    if gateway_online():
        return {"ok": True, "already_running": True}

    app = ROOT / "gateway" / "app.py"
    kwargs = {
        "cwd": ROOT,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        kwargs["start_new_session"] = True

    process = subprocess.Popen([sys.executable, str(app)], **kwargs)
    for _ in range(40):
        time.sleep(0.25)
        if gateway_online():
            return {"ok": True, "pid": process.pid}
    return {
        "ok": False,
        "pid": process.pid,
        "message": "gateway health-check failed",
    }


def start_main() -> dict:
    current = manager.status("main")
    if current.get("online"):
        return {"ok": True, "already_running": True, "pid": current.get("pid")}

    app = ROOT / "core" / "main" / "app.py"
    kwargs = {
        "cwd": ROOT,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        kwargs["start_new_session"] = True

    process = subprocess.Popen([sys.executable, str(app)], **kwargs)
    for _ in range(40):
        time.sleep(0.25)
        if manager.status("main").get("online"):
            return {"ok": True, "pid": process.pid}
    return {"ok": False, "pid": process.pid, "message": "main health-check failed"}



def stop_main() -> dict:
    manager.set_desired_state("main", "stopped")
    pid = manager.pid("main")
    if pid is None:
        return {"ok": True, "already_stopped": True}

    try:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                return {
                    "ok": False,
                    "pid": pid,
                    "message": result.stderr.strip() or result.stdout.strip(),
                }
        else:
            os.kill(pid, signal.SIGTERM)

        for _ in range(24):
            time.sleep(0.25)
            if not manager.status("main").get("online"):
                return {"ok": True, "pid": pid}
        return {"ok": False, "pid": pid, "message": "main still responds after stop"}
    except Exception as exc:
        return {"ok": False, "pid": pid, "message": str(exc)}


def restart_main() -> dict:
    manager.set_desired_state("main", "running")
    pid = manager.pid("main")
    if pid is not None:
        stopped = stop_main()
        if not stopped.get("ok"):
            return stopped
    manager.set_desired_state("main", "running")
    return start_main()


def lifecycle_action(name: str, action: str) -> dict:
    if name not in cores:
        return {"ok": False, "error": "unknown_core", "core": name}

    if action not in {"start", "stop", "restart"}:
        return {"ok": False, "error": "unsupported_action", "action": action}

    if name == "main":
        if action == "start":
            manager.set_desired_state("main", "running")
            return start_main()
        if action == "stop":
            return stop_main()
        return restart_main()

    handler = getattr(manager, action)
    return handler(name)


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
    with deployment_lock:
        deployments = {
            name: {
                "candidate": data["candidate"].__dict__,
                "previous": data["previous"],
            }
            for name, data in active_deployments.items()
        }

    return {
        "service": "supervisor",
        "status": "ok",
        "uptime_seconds": int(time.monotonic() - started),
        "safe_mode": safe_mode(),
        "gateway": {
            "enabled": gateway_enabled,
            "online": gateway_online(),
            "host": gateway_host,
            "port": gateway_port,
        },
        "cores": manager.snapshot(),
        "deployments": deployments,
        "restart_budget": {
            "window_seconds": crash_loop_window_seconds,
            "max_restarts": max_restarts_in_window,
            "history": {name: len(values) for name, values in restart_history.items()},
        },
    }


def restart_allowed(name: str) -> bool:
    now = time.monotonic()
    history = [
        stamp
        for stamp in restart_history[name]
        if now - stamp <= crash_loop_window_seconds
    ]
    restart_history[name] = history
    if len(history) >= max_restarts_in_window:
        set_safe_mode(
            True,
            f"crash_loop:{name}:{len(history)}_restarts_in_{crash_loop_window_seconds}s",
        )
        logger.error("Crash loop detected for %s; entering safe mode", name)
        return False
    history.append(now)
    return True


def sync_active_routes() -> None:
    with deployment_lock:
        for core, data in list(active_deployments.items()):
            candidate = data["candidate"]
            previous = data["previous"]
            probe = deployer.probe(
                candidate,
                timeout_seconds=2,
                cleanup_on_failure=False,
            )
            if probe.get("ok"):
                try:
                    deployer.promote(candidate)
                    logger.info("Restored active candidate route for %s", core)
                except Exception:
                    logger.exception("Failed to restore active candidate route for %s", core)
                continue

            try:
                deployer.rollback_route(core, previous)
            except Exception:
                logger.exception("Failed to restore previous route for %s", core)
            active_deployments.pop(core, None)
            delete_deployment(core)
            logger.warning("Dropped unhealthy candidate deployment for %s", core)


def recovery_loop() -> None:
    if startup_grace_seconds:
        time.sleep(startup_grace_seconds)
    while True:
        if safe_mode():
            time.sleep(interval)
            continue

        if gateway_enabled:
            if gateway_online():
                failures["gateway"] = 0
            else:
                failures["gateway"] += 1
                logger.warning(
                    "Supervisor gateway health failure: %s/%s",
                    failures["gateway"],
                    failure_threshold,
                )
                if failures["gateway"] >= failure_threshold:
                    if restart_allowed("gateway"):
                        result = start_gateway()
                        logger.warning("Supervisor gateway recovery: %s", result)
                        if result.get("ok"):
                            sync_active_routes()
                    failures["gateway"] = 0

        for name in cores:
            if manager.desired_state(name) == "stopped":
                failures[name] = 0
                continue

            with deployment_lock:
                deployment_active = name in active_deployments
            if deployment_active:
                failures[name] = 0
                continue

            if manager.is_online(name):
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
                if not restart_allowed(name):
                    failures[name] = 0
                    break
                if name == "main":
                    result = start_main()
                else:
                    result = manager.restart(name)
                logger.warning("Supervisor recovery %s: %s", name, result)
                failures[name] = 0

        time.sleep(interval)


def persist_deployment(core: str, candidate: Candidate, previous: dict) -> None:
    db.execute(
        """
        INSERT INTO deployment_state(core_name, candidate_json, previous_json, created_at)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(core_name) DO UPDATE SET
            candidate_json=excluded.candidate_json,
            previous_json=excluded.previous_json,
            created_at=excluded.created_at
        """,
        (
            core,
            json.dumps(candidate.__dict__, ensure_ascii=False),
            json.dumps(previous, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def delete_deployment(core: str) -> None:
    db.execute(
        "DELETE FROM deployment_state WHERE core_name=?",
        (core,),
    )


def restore_deployments() -> None:
    rows = db.query(
        """
        SELECT core_name, candidate_json, previous_json
        FROM deployment_state
        ORDER BY core_name
        """
    )
    for row in rows:
        core = row["core_name"]
        try:
            candidate = Candidate(**json.loads(row["candidate_json"]))
            previous = json.loads(row["previous_json"])
            probe = deployer.probe(candidate, timeout_seconds=2)
            if not probe.get("ok"):
                try:
                    deployer.rollback_route(core, previous)
                except Exception:
                    logger.exception("Failed to restore previous route for %s", core)
                delete_deployment(core)
                continue

            active_deployments[core] = {
                "candidate": candidate,
                "previous": previous,
            }
            try:
                deployer.promote(candidate)
            except Exception:
                logger.exception("Failed to re-sync candidate route for %s", core)
        except Exception:
            logger.exception("Failed to restore deployment state for %s", core)


def deploy_candidate(core: str, port: int) -> dict:
    if safe_mode():
        return {"ok": False, "error": "safe_mode_enabled"}

    with deployment_lock:
        existing = active_deployments.get(core)
        if existing:
            return {
                "ok": False,
                "error": "deployment_already_active",
                "candidate": existing["candidate"].__dict__,
            }

        result = deployer.stage_and_promote(core, int(port))
        if not result.get("ok"):
            return result

        candidate = Candidate(**result["candidate"])
        previous = result["route"]["previous"]
        active_deployments[core] = {
            "candidate": candidate,
            "previous": previous,
        }
        persist_deployment(core, candidate, previous)
        return result


def rollback_deployment(core: str) -> dict:
    with deployment_lock:
        data = active_deployments.get(core)
        if not data:
            return {"ok": False, "error": "deployment_not_found", "core": core}

        candidate = data["candidate"]
        previous = data["previous"]
        route = deployer.rollback_route(core, previous)
        terminated = deployer.terminate(candidate)
        active_deployments.pop(core, None)
        delete_deployment(core)
        return {
            "ok": True,
            "core": core,
            "route": route,
            "candidate_terminated": terminated,
        }


def complete_deployment(core: str) -> dict:
    with deployment_lock:
        data = active_deployments.get(core)
        if not data:
            return {"ok": False, "error": "deployment_not_found", "core": core}

        entry = cores.get(core)
        if entry is None:
            return {"ok": False, "error": "unknown_core", "core": core}
        canonical_port = int(entry["port"] if isinstance(entry, dict) else entry)

        if not manager.is_online(core):
            return {
                "ok": False,
                "error": "canonical_not_ready",
                "core": core,
                "canonical_port": canonical_port,
            }

        candidate = data["candidate"]
        route = deployer.rollback_route(
            core,
            {
                "host": host,
                "port": canonical_port,
                "slot": "canonical",
            },
        )
        terminated = deployer.terminate(candidate)
        active_deployments.pop(core, None)
        delete_deployment(core)
        return {
            "ok": True,
            "core": core,
            "route": route,
            "candidate_terminated": terminated,
        }


class Handler(BaseHTTPRequestHandler):
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
        if self.path == "/deployments":
            if not self.authorized():
                self.send_json(401, {"error": "unauthorized"})
                return
            self.send_json(200, {"deployments": snapshot()["deployments"]})
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if not self.authorized():
            self.send_json(401, {"error": "unauthorized"})
            return
        if self.path == "/safe-mode/enable":
            set_safe_mode(True, "api_request")
            self.send_json(200, {"safe_mode": True})
            return
        if self.path == "/safe-mode/disable":
            set_safe_mode(False)
            self.send_json(200, {"safe_mode": False})
            return
        if self.path == "/core/action":
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                name = str(payload.get("core", "")).strip()
                action = str(payload.get("action", "")).strip().lower()
                result = lifecycle_action(name, action)
                self.send_json(200 if result.get("ok") else 409, result)
            except json.JSONDecodeError:
                self.send_json(400, {"error": "invalid_json"})
            return

        if self.path in {
            "/deployment/promote",
            "/deployment/rollback",
            "/deployment/complete",
        }:
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                core = str(payload.get("core", "")).strip()
                if self.path == "/deployment/promote":
                    result = deploy_candidate(core, int(payload.get("port")))
                elif self.path == "/deployment/rollback":
                    result = rollback_deployment(core)
                else:
                    result = complete_deployment(core)
                self.send_json(200 if result.get("ok") else 409, result)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": "invalid_deployment_request", "message": str(exc)})
            return

        self.send_json(404, {"error": "not_found"})

    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)


def main() -> int:
    db.initialize(str(config.get("version", "0.3.0-alpha")))
    restore_deployments()
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
