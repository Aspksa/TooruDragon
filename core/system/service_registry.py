from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
import time


class ServiceRegistry:
    def __init__(self, stale_after_seconds: int = 35):
        self.stale_after_seconds = max(5, stale_after_seconds)
        self._services: dict[str, dict] = {}
        self._lock = Lock()

    def register(self, payload: dict) -> dict:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("service name is required")

        now = time.time()
        record = {
            "name": name,
            "display_name": str(payload.get("display_name", name)),
            "version": str(payload.get("version", "0.0.0")),
            "host": str(payload.get("host", "127.0.0.1")),
            "port": int(payload.get("port", 0)),
            "role": str(payload.get("role", "")),
            "capabilities": list(payload.get("capabilities", [])),
            "pid": payload.get("pid"),
            "uptime_seconds": int(payload.get("uptime_seconds", 0)),
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "_last_seen_epoch": now,
        }

        with self._lock:
            previous = self._services.get(name)
            if previous and previous.get("registered_at"):
                record["registered_at"] = previous["registered_at"]
            else:
                record["registered_at"] = record["last_seen_at"]
            self._services[name] = record

        return self._public(record, now)

    def _public(self, record: dict, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        age = max(0.0, now - float(record.get("_last_seen_epoch", now)))
        result = {key: value for key, value in record.items() if not key.startswith("_")}
        result["heartbeat_age_seconds"] = round(age, 1)
        result["status"] = "online" if age <= self.stale_after_seconds else "stale"
        return result

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            services = {
                name: self._public(record, now)
                for name, record in self._services.items()
            }

        online = sum(1 for item in services.values() if item["status"] == "online")
        return {
            "stale_after_seconds": self.stale_after_seconds,
            "registered": len(services),
            "online": online,
            "services": services,
        }
