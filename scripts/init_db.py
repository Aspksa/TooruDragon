from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "toorudragon.db"
SCHEMA_PATH = DATA_DIR / "schema.sql"


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(DB_PATH) as db:
        db.executescript(schema)
        db.execute(
            "INSERT OR REPLACE INTO system_meta(key, value) VALUES(?, ?)",
            ("version", "0.1.0-alpha"),
        )
        db.execute(
            "INSERT OR REPLACE INTO system_meta(key, value) VALUES(?, ?)",
            ("initialized_at", datetime.now(timezone.utc).isoformat()),
        )
        db.commit()

    print(f"[DB] Ready: {DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
