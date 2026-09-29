from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .database import Database


TERMINAL_STATES = {"completed", "failed", "cancelled"}
ACTIVE_STATES = {"queued", "claimed", "running", "retrying", "waiting"}
ALL_STATES = {"created", *ACTIVE_STATES, *TERMINAL_STATES}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or utcnow()).isoformat()


class WorkflowEngine:
    def __init__(self, database: Database | None = None):
        self.db = database or Database()

    def _transition(
        self,
        db,
        task_id: str,
        from_state: str,
        to_state: str,
        *,
        message: str = "",
    ) -> None:
        db.execute(
            """
            INSERT INTO task_transitions(task_id, from_state, to_state, message, created_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (task_id, from_state, to_state, message, iso()),
        )

    def create_task(
        self,
        *,
        kind: str,
        payload: dict,
        workflow_id: str | None = None,
        parent_id: str | None = None,
        priority: int = 100,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
        available_at: str | None = None,
        trace_id: str | None = None,
        required_capability: str | None = None,
    ) -> dict:
        if not kind.strip():
            raise ValueError("task kind is required")
        if not isinstance(payload, dict):
            raise TypeError("payload must be an object")

        task_id = str(uuid4())
        workflow_id = workflow_id or str(uuid4())
        trace_id = trace_id or str(uuid4())
        now = iso()
        available_at = available_at or now

        with self.db.connect() as db:
            if idempotency_key:
                row = db.execute(
                    """
                    SELECT * FROM tasks
                    WHERE idempotency_key = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (idempotency_key,),
                ).fetchone()
                if row:
                    return self._row(dict(row))

            db.execute(
                """
                INSERT INTO tasks(
                    id, workflow_id, parent_id, kind, payload_json, state,
                    priority, attempts, max_attempts, available_at,
                    lease_owner, lease_until, idempotency_key, trace_id,
                    required_capability, result_json, error,
                    created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, 'queued', ?, 0, ?, ?, NULL, NULL, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (
                    task_id,
                    workflow_id,
                    parent_id,
                    kind,
                    json.dumps(payload, ensure_ascii=False),
                    int(priority),
                    max(1, int(max_attempts)),
                    available_at,
                    idempotency_key,
                    trace_id,
                    required_capability,
                    now,
                    now,
                ),
            )
            self._transition(db, task_id, "created", "queued", message="task_created")

        return self.get(task_id)

    def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 60,
        kinds: list[str] | None = None,
        allowed_capabilities: set[str] | None = None,
    ) -> dict | None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")

        now_dt = utcnow()
        now = iso(now_dt)
        lease_until = iso(now_dt + timedelta(seconds=max(5, int(lease_seconds))))

        where = """
            tasks.state IN ('queued', 'retrying')
            AND tasks.available_at <= ?
            AND (tasks.lease_until IS NULL OR tasks.lease_until < ?)
            AND (
                tasks.parent_id IS NULL
                OR EXISTS (
                    SELECT 1
                    FROM tasks AS parent
                    WHERE parent.id = tasks.parent_id
                      AND parent.state = 'completed'
                )
            )
        """
        params: list = [now, now]
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            where += f" AND kind IN ({placeholders})"
            params.extend(kinds)

        if allowed_capabilities is not None:
            capabilities = sorted(allowed_capabilities)
            if capabilities:
                placeholders = ",".join("?" for _ in capabilities)
                where += f" AND (required_capability IS NULL OR required_capability IN ({placeholders}))"
                params.extend(capabilities)
            else:
                where += " AND required_capability IS NULL"

        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                f"""
                SELECT tasks.* FROM tasks
                WHERE {where}
                ORDER BY tasks.priority ASC, tasks.created_at ASC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
            if not row:
                return None

            task = dict(row)
            updated = db.execute(
                """
                UPDATE tasks
                SET state='claimed',
                    lease_owner=?,
                    lease_until=?,
                    attempts=attempts+1,
                    updated_at=?
                WHERE id=?
                  AND state IN ('queued', 'retrying')
                  AND (lease_until IS NULL OR lease_until < ?)
                """,
                (worker_id, lease_until, now, task["id"], now),
            )
            if updated.rowcount != 1:
                return None

            self._transition(
                db,
                task["id"],
                task["state"],
                "claimed",
                message=f"worker={worker_id}",
            )

        return self.get(task["id"])

    def mark_running(self, task_id: str, worker_id: str) -> dict:
        return self._owned_transition(task_id, worker_id, "claimed", "running")

    def heartbeat(self, task_id: str, worker_id: str, lease_seconds: int = 60) -> dict:
        now = utcnow()
        until = iso(now + timedelta(seconds=max(5, int(lease_seconds))))
        with self.db.connect() as db:
            updated = db.execute(
                """
                UPDATE tasks
                SET lease_until=?, updated_at=?
                WHERE id=? AND lease_owner=? AND state IN ('claimed','running')
                """,
                (until, iso(now), task_id, worker_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("task lease is not owned by worker")
        return self.get(task_id)

    def complete(self, task_id: str, worker_id: str, result: dict | None = None) -> dict:
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise KeyError(task_id)
            task = dict(row)
            if task["lease_owner"] != worker_id or task["state"] not in {"claimed", "running"}:
                raise RuntimeError("task lease is not owned by worker")

            db.execute(
                """
                UPDATE tasks
                SET state='completed', result_json=?, error=NULL,
                    lease_owner=NULL, lease_until=NULL, updated_at=?
                WHERE id=?
                """,
                (json.dumps(result or {}, ensure_ascii=False), iso(), task_id),
            )
            self._transition(db, task_id, task["state"], "completed", message="task_completed")
        return self.get(task_id)

    def _cancel_descendants(self, db, parent_id: str, reason: str) -> int:
        pending = [parent_id]
        cancelled = 0
        while pending:
            current = pending.pop()
            children = db.execute(
                """
                SELECT id, state
                FROM tasks
                WHERE parent_id=?
                  AND state NOT IN ('completed','failed','cancelled')
                """,
                (current,),
            ).fetchall()
            for child in children:
                child_id = child["id"]
                child_state = child["state"]
                db.execute(
                    """
                    UPDATE tasks
                    SET state='cancelled',
                        error=?,
                        lease_owner=NULL,
                        lease_until=NULL,
                        updated_at=?
                    WHERE id=?
                    """,
                    (reason, iso(), child_id),
                )
                self._transition(
                    db,
                    child_id,
                    child_state,
                    "cancelled",
                    message=reason,
                )
                pending.append(child_id)
                cancelled += 1
        return cancelled

    def fail(
        self,
        task_id: str,
        worker_id: str,
        error: str,
        *,
        retry_delay_seconds: int = 5,
    ) -> dict:
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise KeyError(task_id)
            task = dict(row)
            if task["lease_owner"] != worker_id or task["state"] not in {"claimed", "running"}:
                raise RuntimeError("task lease is not owned by worker")

            can_retry = int(task["attempts"]) < int(task["max_attempts"])
            target = "retrying" if can_retry else "failed"
            available_at = iso(utcnow() + timedelta(seconds=max(0, retry_delay_seconds)))

            db.execute(
                """
                UPDATE tasks
                SET state=?, error=?, available_at=?,
                    lease_owner=NULL, lease_until=NULL, updated_at=?
                WHERE id=?
                """,
                (target, error, available_at, iso(), task_id),
            )
            self._transition(db, task_id, task["state"], target, message=error[:1000])
            if target == "failed":
                self._cancel_descendants(
                    db,
                    task_id,
                    reason=f"dependency_failed:{task_id}",
                )

        return self.get(task_id)

    def cancel(self, task_id: str, reason: str = "cancelled") -> dict:
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise KeyError(task_id)
            task = dict(row)
            if task["state"] in TERMINAL_STATES:
                return self._row(task)

            db.execute(
                """
                UPDATE tasks
                SET state='cancelled', error=?,
                    lease_owner=NULL, lease_until=NULL, updated_at=?
                WHERE id=?
                """,
                (reason, iso(), task_id),
            )
            self._transition(db, task_id, task["state"], "cancelled", message=reason)
            self._cancel_descendants(
                db,
                task_id,
                reason=f"dependency_cancelled:{task_id}",
            )
        return self.get(task_id)

    def requeue_expired(self) -> int:
        now = iso()
        with self.db.connect() as db:
            rows = db.execute(
                """
                SELECT id, state FROM tasks
                WHERE state IN ('claimed','running')
                  AND lease_until IS NOT NULL
                  AND lease_until < ?
                """,
                (now,),
            ).fetchall()
            for row in rows:
                db.execute(
                    """
                    UPDATE tasks
                    SET state='retrying', lease_owner=NULL, lease_until=NULL,
                        available_at=?, error='lease_expired', updated_at=?
                    WHERE id=?
                    """,
                    (now, now, row["id"]),
                )
                self._transition(
                    db,
                    row["id"],
                    row["state"],
                    "retrying",
                    message="lease_expired",
                )
            return len(rows)

    def get(self, task_id: str) -> dict:
        rows = self.db.query("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not rows:
            raise KeyError(task_id)
        return self._row(rows[0])

    def list_tasks(
        self,
        *,
        state: str | None = None,
        workflow_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        clauses = []
        params: list = []
        if state:
            if state not in ALL_STATES:
                raise ValueError("unknown task state")
            clauses.append("state=?")
            params.append(state)
        if workflow_id:
            clauses.append("workflow_id=?")
            params.append(workflow_id)

        sql = "SELECT * FROM tasks"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        return [self._row(row) for row in self.db.query(sql, tuple(params))]

    def transitions(self, task_id: str) -> list[dict]:
        return self.db.query(
            """
            SELECT id, task_id, from_state, to_state, message, created_at
            FROM task_transitions
            WHERE task_id=?
            ORDER BY id ASC
            """,
            (task_id,),
        )

    def _owned_transition(
        self,
        task_id: str,
        worker_id: str,
        expected: str,
        target: str,
    ) -> dict:
        with self.db.connect() as db:
            updated = db.execute(
                """
                UPDATE tasks
                SET state=?, updated_at=?
                WHERE id=? AND lease_owner=? AND state=?
                """,
                (target, iso(), task_id, worker_id, expected),
            )
            if updated.rowcount != 1:
                raise RuntimeError("invalid task state or lease owner")
            self._transition(db, task_id, expected, target)
        return self.get(task_id)

    @staticmethod
    def _row(row: dict) -> dict:
        result = dict(row)
        for field in ("payload_json", "result_json"):
            raw = result.pop(field, None)
            result[field.removesuffix("_json")] = json.loads(raw) if raw else None
        return result
