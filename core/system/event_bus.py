from __future__ import annotations

from .database import Database
from .event_fabric import EventFabric


class EventBus:
    """
    Backward-compatible facade over the durable Event Fabric.
    Existing callers keep publish()/recent(); new code may use replay/ack/DLQ.
    """

    def __init__(self, max_events: int = 500, database: Database | None = None):
        self.fabric = EventFabric(
            database=database or Database(),
            retention=max(1000, int(max_events)),
        )

    def publish(
        self,
        topic: str,
        source: str,
        payload: dict | None = None,
        *,
        trace_id: str | None = None,
    ) -> dict:
        return self.fabric.publish(
            topic,
            source,
            payload,
            trace_id=trace_id,
        )

    def recent(
        self,
        limit: int = 50,
        topic: str | None = None,
        *,
        after_sequence: int | None = None,
    ) -> list[dict]:
        return self.fabric.recent(
            limit=limit,
            topic=topic,
            after_sequence=after_sequence,
        )

    def replay(
        self,
        consumer: str,
        *,
        topic: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return self.fabric.replay(consumer, topic=topic, limit=limit)

    def ack(self, consumer: str, sequence: int) -> None:
        self.fabric.ack(consumer, sequence)

    def dead_letter(self, event_id: str, consumer: str, error: str) -> dict:
        return self.fabric.dead_letter(event_id, consumer, error)

    def consumers(self) -> list[dict]:
        return self.fabric.consumer_status()

    def stats(self) -> dict:
        return self.fabric.stats()
