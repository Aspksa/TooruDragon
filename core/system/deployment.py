from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import system_config
from .paths import ROOT


@dataclass(frozen=True)
class Candidate:
    core: str
    port: int
    pid: int
    started_at: float


class DeploymentCoordinator:
    """
    Blue/green groundwork.

    Current cores still bind fixed ports by configuration. This coordinator stages
    a candidate by injecting TOORUDRAGON_PORT_OVERRIDE. Cores that adopt the
    override can be health-checked before promotion. Traffic switching remains a
    separate router concern, so this class deliberately does not fake zero downtime.
    """

    APP_PATHS = {
        "tooru_ai": "core/tooru_ai/app.py",
        "laboratory": "core/workshop/app.py",
        "home": "core/home/app.py",
        "work": "core/work/app.py",
        "mobile": "core/mobile/app.py",
    }

    def __init__(self, root: Path = ROOT):
        self.root = root
        config = system_config()
        gateway = config.get("gateway", {})
        self.gateway_host = str(gateway.get("host", "127.0.0.1"))
        self.gateway_port = int(gateway.get("port", 8698))
        self.token = str(config.get("auth", {}).get("token", ""))

    def stage(self, core: str, port: int) -> Candidate:
        path = self.APP_PATHS.get(core)
        if not path:
            raise ValueError(f"unsupported core: {core}")

        env = dict(os.environ)
        env["TOORUDRAGON_PORT_OVERRIDE"] = str(int(port))
        env["TOORUDRAGON_DISABLE_REGISTRY"] = "1"
        kwargs = {
            "cwd": self.root,
            "env": env,
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

        process = subprocess.Popen(
            [sys.executable, str(self.root / path)],
            **kwargs,
        )
        return Candidate(
            core=core,
            port=int(port),
            pid=process.pid,
            started_at=time.time(),
        )

    def probe(
        self,
        candidate: Candidate,
        timeout_seconds: int = 15,
        *,
        cleanup_on_failure: bool = True,
    ) -> dict:
        deadline = time.monotonic() + timeout_seconds
        url = f"http://127.0.0.1:{candidate.port}/health"
        last_error = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1.0) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    if response.status == 200 and payload.get("status") == "ok":
                        return {
                            "ok": True,
                            "candidate": candidate.__dict__,
                            "health": payload,
                        }
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = str(exc)
            time.sleep(0.25)
        cleaned_up = self.terminate(candidate) if cleanup_on_failure else False
        return {
            "ok": False,
            "candidate": candidate.__dict__,
            "error": last_error or "candidate did not become ready",
            "cleaned_up": cleaned_up,
        }

    def route(self, core: str) -> dict:
        request = urllib.request.Request(
            f"http://{self.gateway_host}:{self.gateway_port}/routes",
            method="GET",
            headers=self._gateway_headers(),
        )
        with urllib.request.urlopen(request, timeout=3.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        route = payload.get("routes", {}).get(core)
        if not route:
            raise KeyError(core)
        return {
            "generation": payload.get("generation"),
            "route": route,
        }

    def promote(
        self,
        candidate: Candidate,
        *,
        slot: str = "green",
    ) -> dict:
        payload = json.dumps(
            {
                "core": candidate.core,
                "host": "127.0.0.1",
                "port": candidate.port,
                "slot": slot,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://{self.gateway_host}:{self.gateway_port}/routes/promote",
            data=payload,
            method="POST",
            headers={
                **self._gateway_headers(),
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=3.0) as response:
            return json.loads(response.read().decode("utf-8"))

    def rollback_route(self, core: str, previous: dict) -> dict:
        payload = json.dumps(
            {
                "core": core,
                "host": previous["host"],
                "port": int(previous["port"]),
                "slot": previous.get("slot", "canonical"),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://{self.gateway_host}:{self.gateway_port}/routes/promote",
            data=payload,
            method="POST",
            headers={
                **self._gateway_headers(),
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=3.0) as response:
            return json.loads(response.read().decode("utf-8"))

    def stage_and_promote(
        self,
        core: str,
        port: int,
        *,
        timeout_seconds: int = 15,
    ) -> dict:
        candidate = self.stage(core, port)
        probe = self.probe(candidate, timeout_seconds=timeout_seconds)
        if not probe.get("ok"):
            return {
                "ok": False,
                "phase": "probe",
                "candidate": candidate.__dict__,
                "probe": probe,
            }

        try:
            promoted = self.promote(candidate)
        except Exception as exc:
            self.terminate(candidate)
            return {
                "ok": False,
                "phase": "promote",
                "candidate": candidate.__dict__,
                "error": str(exc),
                "cleaned_up": True,
            }

        return {
            "ok": True,
            "phase": "promoted",
            "candidate": candidate.__dict__,
            "route": promoted,
        }

    def _gateway_headers(self) -> dict:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def terminate(self, candidate: Candidate) -> bool:
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["taskkill", "/PID", str(candidate.pid), "/T", "/F"],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                return result.returncode == 0
            os.kill(candidate.pid, signal.SIGTERM)
            return True
        except (OSError, ProcessLookupError):
            return False
