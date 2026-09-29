from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import system_config
from .paths import DATA_DIR, ROOT, SCHEMA_PATH


class Database:
    def __init__(self, path: Path | None = None):
        if path is None:
            configured = system_config().get("database", {}).get(
                "path",
                "data/toorudragon.db",
            )
            path = ROOT / configured
        self.path = Path(path)

    def initialize(self, version: str) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        with sqlite3.connect(self.path, timeout=10) as db:
            db.executescript(schema)
            db.execute(
                "INSERT OR REPLACE INTO system_meta(key, value) VALUES(?, ?)",
                ("version", version),
            )
            db.execute(
                "INSERT OR REPLACE INTO system_meta(key, value) VALUES(?, ?)",
                ("initialized_at", datetime.now(timezone.utc).isoformat()),
            )
            db.commit()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self.connect() as db:
            cursor = db.execute(sql, params)
            return cursor.lastrowid
