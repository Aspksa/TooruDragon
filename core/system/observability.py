from __future__ import annotations

import os
import resource
import time
from collections import deque
from threading import Lock


class Observability:
    def __init__(self, max_samples: int = 300):
        self.started = time.monotonic()
        self._samples = deque(maxlen=max(10, max_samples))
        self._lock = Lock()
        self._counters: dict[str, int] = {}

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + int(value)

    def sample(self) -> dict:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss = int(getattr(usage, "ru_maxrss", 0))
        if os.name != "nt":
            rss *= 1024
        value = {
            "uptime_seconds": int(time.monotonic() - self.started),
            "pid": os.getpid(),
            "rss_bytes": rss,
            "user_cpu_seconds": round(float(usage.ru_utime), 3),
            "system_cpu_seconds": round(float(usage.ru_stime), 3),
            "counters": dict(self._counters),
        }
        with self._lock:
            self._samples.append(value)
        return value

    def snapshot(self) -> dict:
        current = self.sample()
        with self._lock:
            history = list(self._samples)[-30:]
        return {"current": current, "recent": history}
