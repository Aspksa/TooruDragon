from __future__ import annotations

import os
import time
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class SupervisorSnapshot:
    mode: str
    pid: int
    uptime_seconds: int
    safe_mode: bool
    architecture_version: str


class SupervisorFacade:
    """
    Stable control-plane boundary.

    In Alpha this facade lives in-process. A future Rust Windows service/Linux
    daemon can implement the same contract without changing Main Core callers.
    """

    def __init__(self, architecture_version: str = "0.2"):
        self._started = time.monotonic()
        self.architecture_version = architecture_version
        self.safe_mode = False

    def enter_safe_mode(self) -> None:
        self.safe_mode = True

    def leave_safe_mode(self) -> None:
        self.safe_mode = False

    def snapshot(self) -> dict:
        return asdict(
            SupervisorSnapshot(
                mode="embedded",
                pid=os.getpid(),
                uptime_seconds=int(time.monotonic() - self._started),
                safe_mode=self.safe_mode,
                architecture_version=self.architecture_version,
            )
        )
