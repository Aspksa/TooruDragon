from __future__ import annotations

import json
import urllib.error
import urllib.request


class EventBusClient:
    def __init__(self, base_url: str, token: str = "", logger=None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.logger = logger

    def publish(self, topic: str, source: str, payload: dict | None = None) -> bool:
        body = json.dumps(
            {
                "topic": topic,
                "source": source,
                "payload": payload or {},
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}/events/publish",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")

        try:
            with urllib.request.urlopen(request, timeout=2.0) as response:
                return response.status in (200, 201, 202)
        except (urllib.error.URLError, TimeoutError) as exc:
            if self.logger:
                self.logger.warning("Event Bus publish failed: %s", exc)
            return False
