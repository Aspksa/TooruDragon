from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from .database import Database


class EventFabric:
    def __init__(self, database: Database | None = None, retention: int = 10000):
        self.db = database or Database()
        self.retention = max(1000, int(retention))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def publish(
        self,
        topic: str,
        source: str,
        payload: dict | None = None,
        *,
        trace_id: str | None = None,
        event_id: str | None = None,
    ) -> dict:
        if not topic.strip():
            raise ValueError("topic is required")
        if not source.strip():
            raise ValueError("source is required")
        event_id = event_id or str(uuid4())
        trace_id = trace_id or str(uuid4())
        created_at = self._now()
        self.db.execute(
            """
            INSERT INTO durable_events(id, topic, source, payload_json, trace_id, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                topic,
                source,
                json.dumps(payload or {}, ensure_ascii=False),
                trace_id,
                created_at,
            ),
        )
        self._prune()
        return self.get(event_id)

    def get(self, event_id: str) -> dict:
        rows = self.db.query(
            """
            SELECT sequence, id, topic, source, payload_json, trace_id, created_at
            FROM durable_events
            WHERE id=?
            """,
            (event_id,),
        )
        if not rows:
            raise KeyError(event_id)
        return self._decode(rows[0])

    def recent(
        self,
        limit: int = 50,
        topic: str | None = None,
        *,
        after_sequence: int | None = None,
    ) -> list[dict]:
        clauses = []
        params: list = []
        if topic:
            clauses.append("topic=?")
            params.append(topic)
        if after_sequence is not None:
            clauses.append("sequence>?")
            params.append(int(after_sequence))

        sql = """
            SELECT sequence, id, topic, source, payload_json, trace_id, created_at
            FROM durable_events
        """
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY sequence DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        rows = self.db.query(sql, tuple(params))
        return [self._decode(row) for row in rows]

    def replay(
        self,
        consumer: str,
        *,
        topic: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        offsets = self.db.query(
            "SELECT sequence FROM event_offsets WHERE consumer=?",
            (consumer,),
        )
        after = int(offsets[0]["sequence"]) if offsets else 0
        events = self.recent(
            limit=limit,
            topic=topic,
            after_sequence=after,
        )
        return list(reversed(events))

    def ack(self, consumer: str, sequence: int) -> None:
        if not consumer.strip():
            raise ValueError("consumer is required")
        now = self._now()
        with self.db.connect() as db:
            db.execute(
                """
                INSERT INTO event_offsets(consumer, sequence, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(consumer) DO UPDATE SET
                    sequence=MAX(event_offsets.sequence, excluded.sequence),
                    updated_at=excluded.updated_at
                """,
                (consumer, int(sequence), now),
            )

    def dead_letter(
        self,
        event_id: str,
        consumer: str,
        error: str,
    ) -> dict:
        event = self.get(event_id)
        self.db.execute(
            """
            INSERT INTO event_dead_letters(
                event_id, consumer, error, payload_json, created_at
            )
            VALUES(?, ?, ?, ?, ?)
            """,
            (
                event_id,
                consumer,
                error[:4000],
                json.dumps(event, ensure_ascii=False),
                self._now(),
            ),
        )
        return event

    def consumer_status(self) -> list[dict]:
        bounds = self.db.query(
            """
            SELECT
                COALESCE(MIN(sequence), 0) AS earliest,
                COALESCE(MAX(sequence), 0) AS latest
            FROM durable_events
            """
        )[0]
        earliest = int(bounds["earliest"])
        latest = int(bounds["latest"])
        rows = self.db.query(
            """
            SELECT consumer, sequence, updated_at
            FROM event_offsets
            ORDER BY consumer ASC
            """
        )
        result = []
        for row in rows:
            sequence = int(row["sequence"])
            result.append({
                "consumer": row["consumer"],
                "sequence": sequence,
                "updated_at": row["updated_at"],
                "lag": max(0, latest - sequence),
                "retention_gap": bool(earliest and sequence < earliest - 1),
            })
        return result

    def stats(self) -> dict:
        bounds = self.db.query(
            """
            SELECT
                COUNT(*) AS n,
                COALESCE(MIN(sequence), 0) AS earliest,
                COALESCE(MAX(sequence), 0) AS latest
            FROM durable_events
            """
        )[0]
        dlq = self.db.query("SELECT COUNT(*) AS n FROM event_dead_letters")[0]["n"]
        consumers = self.db.query("SELECT COUNT(*) AS n FROM event_offsets")[0]["n"]
        return {
            "events": int(bounds["n"]),
            "earliest_sequence": int(bounds["earliest"]),
            "latest_sequence": int(bounds["latest"]),
            "dead_letters": int(dlq),
            "consumers": int(consumers),
            "retention": self.retention,
        }

    def _prune(self) -> None:
        self.db.execute(
            """
            DELETE FROM durable_events
            WHERE sequence <= (
                SELECT COALESCE(MAX(sequence) - ?, 0)
                FROM durable_events
            )
            """,
            (self.retention,),
        )

    @staticmethod
    def _decode(row: dict) -> dict:
        value = dict(row)
        value["payload"] = json.loads(value.pop("payload_json"))
        return value
