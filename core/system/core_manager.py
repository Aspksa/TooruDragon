from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .database import Database
from .logging import get_logger
from .paths import ROOT


class CoreManager:
    APP_PATHS = {
        "tooru_ai": "core/tooru_ai/app.py",
        "laboratory": "core/workshop/app.py",
        "home": "core/home/app.py",
        "work": "core/work/app.py",
        "mobile": "core/mobile/app.py",
    }

    def __init__(self, host: str, cores: dict, root: Path = ROOT):
        self.host = host
        self.cores = cores
        self.root = root
        self.logger = get_logger("core_manager")
        self.db = Database()

    @staticmethod
    def _utcnow() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _entry(self, name: str) -> dict:
        entry = self.cores.get(name)
        if entry is None:
            raise KeyError(name)
        if isinstance(entry, dict):
            return entry
        return {"port": int(entry)}

    def _port(self, name: str) -> int:
        return int(self._entry(name)["port"])

    def _health(self, name: str) -> dict:
        port = self._port(name)
        url = f"http://{self.host}:{port}/health"
        started = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return {
                    "online": response.status == 200 and payload.get("status") == "ok",
                    "status_code": response.status,
                    "latency_ms": round((time.monotonic() - started) * 1000, 1),
                    "payload": payload,
                }
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return {
                "online": False,
                "error": str(exc),
            }

    def _pid_windows(self, port: int) -> int | None:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return None

        pattern = re.compile(
            rf"^\\s*TCP\\s+\\S*:{port}\\s+\\S+\\s+LISTENING\\s+(\\d+)\\s*$",
            re.IGNORECASE,
        )
        for line in result.stdout.splitlines():
            match = pattern.match(line)
            if match:
                return int(match.group(1))
        return None

    def _pid_posix(self, port: int) -> int | None:
        result = subprocess.run(
            ["sh", "-lc", f"lsof -ti tcp:{port} -sTCP:LISTEN 2>/dev/null | head -n1"],
            text=True,
            capture_output=True,
            check=False,
        )
        value = result.stdout.strip()
        return int(value) if value.isdigit() else None

    def pid(self, name: str) -> int | None:
        port = self._port(name)
        try:
            return self._pid_windows(port) if os.name == "nt" else self._pid_posix(port)
        except (OSError, ValueError):
            return None

    def _set_desired(self, name: str, status: str) -> None:
        self.db.execute(
            """
            INSERT INTO core_state(core_name, status, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(core_name) DO UPDATE SET
                status=excluded.status,
                updated_at=excluded.updated_at
            """,
            (name, status, self._utcnow()),
        )

    def set_desired_state(self, name: str, status: str) -> None:
        if name not in self.cores:
            raise KeyError(name)
        if status not in {"running", "stopped"}:
            raise ValueError("desired state must be running or stopped")
        self._set_desired(name, status)

    def desired_state(self, name: str) -> str:
        rows = self.db.query(
            "SELECT status FROM core_state WHERE core_name=?",
            (name,),
        )
        if not rows:
            return "running"
        return str(rows[0]["status"])

    def _record(self, name: str, action: str, ok: bool, message: str = "") -> None:
        try:
            self.db.execute(
                """
                INSERT INTO core_actions(core_name, action, ok, message, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (name, action, 1 if ok else 0, message, self._utcnow()),
            )
        except Exception:
            self.logger.exception("Failed to record core action: %s %s", name, action)

    def is_online(self, name: str) -> bool:
        return bool(self._health(name).get("online"))

    def status(self, name: str) -> dict:
        entry = self._entry(name)
        health = self._health(name)
        payload = health.get("payload") or {}
        return {
            "name": name,
            "display_name": entry.get("display_name", name),
            "version": payload.get("version") or entry.get("version", "0.0.0"),
            "host": self.host,
            "port": int(entry["port"]),
            "online": bool(health.get("online")),
            "pid": self.pid(name),
            "latency_ms": health.get("latency_ms"),
            "role": payload.get("role"),
            "capabilities": payload.get("capabilities", []),
            "error": health.get("error"),
        }

    def snapshot(self) -> dict:
        return {
            name: self.status(name)
            for name in self.cores
        }

    def _app_path(self, name: str) -> Path:
        relative = self.APP_PATHS.get(name)
        if not relative:
            raise ValueError(f"Core {name!r} cannot be managed by Main Core")
        return self.root / relative

    def start(self, name: str) -> dict:
        if name == "main":
            result = {
                "ok": False,
                "core": name,
                "action": "start",
                "message": "Главное ядро запускается внешним launcher и не управляет собственным процессом.",
            }
            self._record(name, "start", False, result["message"])
            return result

        self._set_desired(name, "running")
        current = self.status(name)
        if current["online"]:
            result = {
                "ok": True,
                "core": name,
                "action": "start",
                "already_running": True,
                "pid": current["pid"],
                "message": "Ядро уже работает.",
            }
            self._record(name, "start", True, result["message"])
            return result

        app = self._app_path(name)
        if not app.exists():
            result = {
                "ok": False,
                "core": name,
                "action": "start",
                "message": f"Не найден файл ядра: {app}",
            }
            self._record(name, "start", False, result["message"])
            return result

        kwargs: dict = {
            "cwd": self.root,
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
            health = self._health(name)
            if health.get("online"):
                result = {
                    "ok": True,
                    "core": name,
                    "action": "start",
                    "pid": self.pid(name) or process.pid,
                    "message": "Ядро запущено.",
                }
                self._record(name, "start", True, result["message"])
                return result

        result = {
            "ok": False,
            "core": name,
            "action": "start",
            "pid": process.pid,
            "message": "Процесс запущен, но ядро не прошло health-check.",
        }
        self._record(name, "start", False, result["message"])
        return result

    def stop(self, name: str) -> dict:
        if name == "main":
            result = {
                "ok": False,
                "core": name,
                "action": "stop",
                "message": "Главное ядро нельзя остановить через собственный HTTP API.",
            }
            self._record(name, "stop", False, result["message"])
            return result

        self._set_desired(name, "stopped")
        pid = self.pid(name)
        if pid is None:
            result = {
                "ok": True,
                "core": name,
                "action": "stop",
                "already_stopped": True,
                "message": "Ядро уже остановлено.",
            }
            self._record(name, "stop", True, result["message"])
            return result

        try:
            if os.name == "nt":
                completed = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if completed.returncode != 0:
                    raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
            else:
                os.kill(pid, signal.SIGTERM)

            for _ in range(24):
                time.sleep(0.25)
                if not self._health(name).get("online"):
                    result = {
                        "ok": True,
                        "core": name,
                        "action": "stop",
                        "pid": pid,
                        "message": "Ядро остановлено.",
                    }
                    self._record(name, "stop", True, result["message"])
                    return result

            raise RuntimeError("Ядро продолжает отвечать после команды остановки.")
        except Exception as exc:
            result = {
                "ok": False,
                "core": name,
                "action": "stop",
                "pid": pid,
                "message": str(exc),
            }
            self._record(name, "stop", False, result["message"])
            return result

    def restart(self, name: str) -> dict:
        if name == "main":
            result = {
                "ok": False,
                "core": name,
                "action": "restart",
                "message": "Перезапуск Main Core должен выполнять внешний launcher/update manager.",
            }
            self._record(name, "restart", False, result["message"])
            return result

        self._set_desired(name, "running")
        stopped = self.stop(name)
        if not stopped.get("ok"):
            return {
                "ok": False,
                "core": name,
                "action": "restart",
                "message": f"Не удалось остановить ядро: {stopped.get('message', '')}",
            }

        self._set_desired(name, "running")
        started = self.start(name)
        result = {
            **started,
            "action": "restart",
        }
        self._record(
            name,
            "restart",
            bool(result.get("ok")),
            result.get("message", ""),
        )
        return result

    def history(self, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        return self.db.query(
            """
            SELECT id, core_name, action, ok, message, created_at
            FROM core_actions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
