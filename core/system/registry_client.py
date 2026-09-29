from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request


class RegistryClient:
    def __init__(
        self,
        base_url: str,
        service: dict,
        token: str = "",
        logger=None,
        heartbeat_seconds: int = 10,
    ):
        self.base_url = base_url.rstrip("/")
        self.service = dict(service)
        self.token = token
        self.logger = logger
        self.heartbeat_seconds = max(3, heartbeat_seconds)
        self.started_at = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _payload(self) -> dict:
        payload = dict(self.service)
        payload["pid"] = os.getpid()
        payload["uptime_seconds"] = int(time.monotonic() - self.started_at)
        return payload

    def register_once(self) -> bool:
        body = json.dumps(self._payload(), ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/registry/register",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")

        try:
            with urllib.request.urlopen(request, timeout=2.0) as response:
                return response.status in (200, 201, 202)
        except (urllib.error.URLError, TimeoutError) as exc:
            if self.logger:
                self.logger.debug("Service Registry heartbeat failed: %s", exc)
            return False

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.register_once()
            self._stop.wait(self.heartbeat_seconds)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop,
            name=f"registry-{self.service.get('name', 'service')}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
