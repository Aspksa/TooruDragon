from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


class Watchdog:
    def __init__(
        self,
        host: str,
        cores: dict,
        root: Path,
        logger,
        interval_seconds: int = 10,
        failure_threshold: int = 3,
        auto_restart: bool = True,
    ):
        self.host = host
        self.cores = cores
        self.root = root
        self.logger = logger
        self.interval_seconds = max(2, interval_seconds)
        self.failure_threshold = max(1, failure_threshold)
        self.auto_restart = auto_restart
        self.failures = {name: 0 for name in cores if name != "main"}
        self.state = {}
        self._stop = threading.Event()
        self._thread = None

    def _port(self, entry) -> int:
        return int(entry["port"] if isinstance(entry, dict) else entry)

    def _probe(self, name: str, entry) -> bool:
        url = f"http://{self.host}:{self._port(entry)}/health"
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
                ok = response.status == 200 and payload.get("status") == "ok"
                self.state[name] = {
                    "ok": ok,
                    "version": payload.get("version"),
                    "url": url,
                }
                return ok
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            self.state[name] = {
                "ok": False,
                "url": url,
                "error": str(exc),
            }
            return False

    def _restart(self, name: str) -> None:
        if not self.auto_restart:
            return
        if os.name != "nt":
            self.logger.warning("Watchdog restart skipped for %s: Windows launcher required", name)
            return

        paths = {
            "tooru_ai": "core\\tooru_ai\\start.bat",
            "laboratory": "core\\workshop\\start.bat",
            "home": "core\\home\\start.bat",
            "work": "core\\work\\start.bat",
            "mobile": "core\\mobile\\start.bat",
        }
        launcher = paths.get(name)
        if not launcher:
            return

        self.logger.warning("Watchdog restarting core: %s", name)
        subprocess.Popen(
            ["cmd", "/c", "start", f"TooruDragon {name}", "cmd", "/k", launcher],
            cwd=self.root,
        )

    def _loop(self) -> None:
        while not self._stop.is_set():
            for name, entry in self.cores.items():
                if name == "main":
                    continue

                if self._probe(name, entry):
                    if self.failures[name]:
                        self.logger.info("Core recovered: %s", name)
                    self.failures[name] = 0
                    continue

                self.failures[name] += 1
                self.logger.warning(
                    "Core %s health failure %s/%s",
                    name,
                    self.failures[name],
                    self.failure_threshold,
                )

                if self.failures[name] >= self.failure_threshold:
                    self._restart(name)
                    self.failures[name] = 0

            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop,
            name="toorudragon-watchdog",
            daemon=True,
        )
        self._thread.start()
        self.logger.info("Watchdog started")

    def snapshot(self) -> dict:
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "auto_restart": self.auto_restart,
            "interval_seconds": self.interval_seconds,
            "failure_threshold": self.failure_threshold,
            "cores": dict(self.state),
        }
