from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4


@dataclass(frozen=True)
class Event:
    id: str
    topic: str
    source: str
    payload: dict
    created_at: str


class EventBus:
    def __init__(self, max_events: int = 500):
        self._events: deque[Event] = deque(maxlen=max_events)
        self._lock = Lock()

    def publish(self, topic: str, source: str, payload: dict | None = None) -> dict:
        event = Event(
            id=str(uuid4()),
            topic=topic,
            source=source,
            payload=payload or {},
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._events.append(event)
        return asdict(event)

    def recent(self, limit: int = 50, topic: str | None = None) -> list[dict]:
        limit = max(1, min(limit, 200))
        with self._lock:
            events = list(self._events)

        if topic:
            events = [event for event in events if event.topic == topic]

        return [asdict(event) for event in events[-limit:]][::-1]
