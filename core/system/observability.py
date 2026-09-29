from __future__ import annotations

import ctypes
import os
import time
from collections import deque
from threading import Lock

try:
    import resource  # POSIX only
except ImportError:
    resource = None


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class Observability:
    def __init__(self, max_samples: int = 300):
        self.started = time.monotonic()
        self._samples = deque(maxlen=max(10, max_samples))
        self._lock = Lock()
        self._counters: dict[str, int] = {}

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + int(value)

    def _windows_rss(self) -> int:
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        )
        return int(counters.WorkingSetSize) if ok else 0

    def _process_stats(self) -> tuple[int, float, float]:
        if os.name == "nt":
            return self._windows_rss(), 0.0, 0.0

        if resource is None:
            return 0, 0.0, 0.0

        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss = int(getattr(usage, "ru_maxrss", 0)) * 1024
        return (
            rss,
            round(float(usage.ru_utime), 3),
            round(float(usage.ru_stime), 3),
        )

    def sample(self) -> dict:
        rss, user_cpu, system_cpu = self._process_stats()
        value = {
            "uptime_seconds": int(time.monotonic() - self.started),
            "pid": os.getpid(),
            "rss_bytes": rss,
            "user_cpu_seconds": user_cpu,
            "system_cpu_seconds": system_cpu,
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
