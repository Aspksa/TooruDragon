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

    def probe(self, candidate: Candidate, timeout_seconds: int = 15) -> dict:
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
        self.terminate(candidate)
        return {
            "ok": False,
            "candidate": candidate.__dict__,
            "error": last_error or "candidate did not become ready",
            "cleaned_up": True,
        }

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
