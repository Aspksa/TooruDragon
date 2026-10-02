from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from .database import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class AdaptiveReasoningStore:
    """Persistent telemetry and feedback-driven tuning for reasoning."""

    def __init__(
        self,
        database: Database,
        *,
        learning_rate: float = 0.15,
        min_weight: float = 0.5,
        max_weight: float = 1.5,
    ):
        self.db = database
        self.learning_rate = max(0.01, min(float(learning_rate), 1.0))
        self.min_weight = float(min_weight)
        self.max_weight = max(float(max_weight), self.min_weight)

    def record_run(
        self,
        *,
        trace_id: str | None,
        mode: str,
        score: int,
        threshold: int,
        branches: list[dict],
        depth: int,
        contradiction_detected: bool,
        fallback: bool,
        metadata: dict | None = None,
    ) -> str:
        run_id = str(uuid4())
        now = _now()
        branch_names = [
            str(item.get("name", "")).strip()
            for item in branches
            if str(item.get("name", "")).strip()
        ]
        with self.db.connect() as db:
            db.execute(
                """
                INSERT INTO reasoning_runs(
                    id, trace_id, mode, score, threshold, branch_count, depth,
                    contradiction_detected, fallback, branch_names_json,
                    metadata_json, feedback_score, feedback_source,
                    created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (
                    run_id,
                    trace_id,
                    mode,
                    int(score),
                    int(threshold),
                    len(branch_names),
                    max(1, int(depth)),
                    1 if contradiction_detected else 0,
                    1 if fallback else 0,
                    json.dumps(branch_names, ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            db.execute(
                """
                INSERT INTO reasoning_mode_stats(
                    mode, runs, feedback_count, feedback_sum, updated_at
                )
                VALUES(?, 1, 0, 0.0, ?)
                ON CONFLICT(mode) DO UPDATE SET
                    runs = runs + 1,
                    updated_at = excluded.updated_at
                """,
                (mode, now),
            )

            for item in branches:
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                status = str(item.get("status", "unknown")).strip() or "unknown"
                db.execute(
                    """
                    INSERT INTO reasoning_run_branches(run_id, branch_name, status)
                    VALUES(?, ?, ?)
                    """,
                    (run_id, name, status),
                )
                db.execute(
                    """
                    INSERT INTO reasoning_branch_stats(
                        branch_name, attempts, completed, failures,
                        feedback_count, feedback_sum, weight, updated_at
                    )
                    VALUES(?, 1, ?, ?, 0, 0.0, 1.0, ?)
                    ON CONFLICT(branch_name) DO UPDATE SET
                        attempts = attempts + 1,
                        completed = completed + excluded.completed,
                        failures = failures + excluded.failures,
                        updated_at = excluded.updated_at
                    """,
                    (
                        name,
                        1 if status == "completed" else 0,
                        1 if status == "failed" else 0,
                        now,
                    ),
                )
        return run_id

    def record_feedback(
        self,
        run_id: str,
        score: float,
        *,
        source: str = "user",
    ) -> dict:
        run_id = str(run_id or "").strip()
        if not run_id:
            raise ValueError("run_id is required")
        score = float(score)
        if score < -1.0 or score > 1.0:
            raise ValueError("feedback score must be between -1 and 1")

        now = _now()
        with self.db.connect() as db:
            row = db.execute(
                """
                SELECT mode, feedback_score
                FROM reasoning_runs
                WHERE id=?
                """,
                (run_id,),
            ).fetchone()
            if not row:
                raise KeyError(run_id)

            old_score = (
                float(row["feedback_score"])
                if row["feedback_score"] is not None
                else None
            )
            delta = score - (old_score or 0.0)
            count_delta = 1 if old_score is None else 0

            db.execute(
                """
                UPDATE reasoning_runs
                SET feedback_score=?, feedback_source=?, updated_at=?
                WHERE id=?
                """,
                (score, str(source or "user"), now, run_id),
            )

            db.execute(
                """
                UPDATE reasoning_mode_stats
                SET feedback_count = feedback_count + ?,
                    feedback_sum = feedback_sum + ?,
                    updated_at = ?
                WHERE mode=?
                """,
                (count_delta, delta, now, row["mode"]),
            )

            branch_rows = db.execute(
                """
                SELECT branch_name
                FROM reasoning_run_branches
                WHERE run_id=?
                """,
                (run_id,),
            ).fetchall()

            for branch_row in branch_rows:
                branch_name = branch_row["branch_name"]
                current = db.execute(
                    """
                    SELECT weight
                    FROM reasoning_branch_stats
                    WHERE branch_name=?
                    """,
                    (branch_name,),
                ).fetchone()
                current_weight = float(current["weight"]) if current else 1.0
                new_weight = _clamp(
                    current_weight + self.learning_rate * delta,
                    self.min_weight,
                    self.max_weight,
                )
                db.execute(
                    """
                    UPDATE reasoning_branch_stats
                    SET feedback_count = feedback_count + ?,
                        feedback_sum = feedback_sum + ?,
                        weight = ?,
                        updated_at = ?
                    WHERE branch_name=?
                    """,
                    (count_delta, delta, new_weight, now, branch_name),
                )

        return self.run(run_id)

    def run(self, run_id: str) -> dict:
        rows = self.db.query(
            """
            SELECT id, trace_id, mode, score, threshold, branch_count, depth,
                   contradiction_detected, fallback, branch_names_json,
                   metadata_json, feedback_score, feedback_source,
                   created_at, updated_at
            FROM reasoning_runs
            WHERE id=?
            """,
            (run_id,),
        )
        if not rows:
            raise KeyError(run_id)
        row = dict(rows[0])
        row["contradiction_detected"] = bool(row["contradiction_detected"])
        row["fallback"] = bool(row["fallback"])
        row["branch_names"] = json.loads(row.pop("branch_names_json") or "[]")
        row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
        return row

    def branch_order(self, branch_names: list[str]) -> list[str]:
        if not branch_names:
            return []
        placeholders = ",".join("?" for _ in branch_names)
        rows = self.db.query(
            f"""
            SELECT branch_name, weight, feedback_count
            FROM reasoning_branch_stats
            WHERE branch_name IN ({placeholders})
            """,
            tuple(branch_names),
        )
        stats = {
            row["branch_name"]: (
                float(row["weight"]),
                int(row["feedback_count"]),
            )
            for row in rows
        }
        original_index = {name: index for index, name in enumerate(branch_names)}
        return sorted(
            branch_names,
            key=lambda name: (
                -stats.get(name, (1.0, 0))[0],
                -stats.get(name, (1.0, 0))[1],
                original_index[name],
            ),
        )

    def threshold_adjustment(self, *, min_feedback: int = 3) -> int:
        rows = self.db.query(
            """
            SELECT mode, feedback_count, feedback_sum
            FROM reasoning_mode_stats
            WHERE mode IN ('chain', 'tree')
            """
        )
        stats = {
            row["mode"]: (
                int(row["feedback_count"]),
                float(row["feedback_sum"]),
            )
            for row in rows
        }
        chain = stats.get("chain", (0, 0.0))
        tree = stats.get("tree", (0, 0.0))
        if chain[0] < min_feedback or tree[0] < min_feedback:
            return 0

        chain_avg = chain[1] / max(1, chain[0])
        tree_avg = tree[1] / max(1, tree[0])
        delta = tree_avg - chain_avg
        if delta >= 0.25:
            return -1
        if delta <= -0.25:
            return 1
        return 0

    def stats(self) -> dict:
        branches = self.db.query(
            """
            SELECT branch_name, attempts, completed, failures,
                   feedback_count, feedback_sum, weight, updated_at
            FROM reasoning_branch_stats
            ORDER BY weight DESC, attempts DESC, branch_name ASC
            """
        )
        for item in branches:
            count = int(item["feedback_count"])
            item["average_feedback"] = (
                round(float(item["feedback_sum"]) / count, 4)
                if count
                else None
            )

        modes = self.db.query(
            """
            SELECT mode, runs, feedback_count, feedback_sum, updated_at
            FROM reasoning_mode_stats
            ORDER BY mode ASC
            """
        )
        for item in modes:
            count = int(item["feedback_count"])
            item["average_feedback"] = (
                round(float(item["feedback_sum"]) / count, 4)
                if count
                else None
            )

        recent = self.db.query(
            """
            SELECT id, trace_id, mode, score, threshold, branch_count, depth,
                   contradiction_detected, fallback, feedback_score, created_at
            FROM reasoning_runs
            ORDER BY created_at DESC
            LIMIT 25
            """
        )
        for item in recent:
            item["contradiction_detected"] = bool(item["contradiction_detected"])
            item["fallback"] = bool(item["fallback"])

        return {
            "threshold_adjustment": self.threshold_adjustment(),
            "branches": branches,
            "modes": modes,
            "recent_runs": recent,
        }
