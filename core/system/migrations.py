from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


WAYBILL_COLUMNS = [
    "id",
    "waybill_number",
    "trip_date",
    "employee_id",
    "vehicle_id",
    "odometer_start",
    "odometer_end",
    "distance_km",
    "fuel_open_l",
    "fuel_issued_l",
    "fuel_close_l",
    "norm_l_per_100km",
    "actual_consumption_l",
    "norm_consumption_l",
    "deviation_l",
    "source_document_id",
    "batch_id",
    "organization",
    "department",
    "vehicle_make",
    "vehicle_model",
    "vehicle_vin",
    "garage_number",
    "driver_name",
    "personnel_number",
    "departure_time",
    "return_time",
    "refueled_l",
    "fuel_name",
    "route",
    "assignment_text",
    "fuel_card_number",
    "source_pages_json",
    "confidence",
    "needs_review",
    "processing_status",
    "folder_path",
    "individual_pdf_path",
    "note",
    "created_at",
    "updated_at",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_columns(db: sqlite3.Connection, table: str) -> list[dict]:
    rows = db.execute(f"PRAGMA table_info({table})").fetchall()
    return [
        {
            "cid": row[0],
            "name": row[1],
            "type": row[2],
            "notnull": row[3],
            "default": row[4],
            "pk": row[5],
        }
        for row in rows
    ]


def _needs_waybill_rebuild(db: sqlite3.Connection) -> bool:
    columns = _table_columns(db, "garage_waybills")
    if not columns:
        return False
    by_name = {item["name"]: item for item in columns}
    if any(name not in by_name for name in WAYBILL_COLUMNS):
        return True
    if by_name["employee_id"]["notnull"] or by_name["vehicle_id"]["notnull"]:
        return True
    if by_name["trip_date"]["notnull"]:
        return True
    return False


def _create_waybill_table(db: sqlite3.Connection, table: str) -> None:
    db.execute(
        f"""
        CREATE TABLE {table} (
            id TEXT PRIMARY KEY,
            waybill_number TEXT NOT NULL DEFAULT '',
            trip_date TEXT,
            employee_id TEXT,
            vehicle_id TEXT,
            odometer_start REAL,
            odometer_end REAL,
            distance_km REAL NOT NULL DEFAULT 0,
            fuel_open_l REAL NOT NULL DEFAULT 0,
            fuel_issued_l REAL NOT NULL DEFAULT 0,
            fuel_close_l REAL NOT NULL DEFAULT 0,
            norm_l_per_100km REAL,
            actual_consumption_l REAL NOT NULL DEFAULT 0,
            norm_consumption_l REAL,
            deviation_l REAL,
            source_document_id TEXT,
            batch_id TEXT,
            organization TEXT NOT NULL DEFAULT '',
            department TEXT NOT NULL DEFAULT '',
            vehicle_make TEXT NOT NULL DEFAULT '',
            vehicle_model TEXT NOT NULL DEFAULT '',
            vehicle_vin TEXT NOT NULL DEFAULT '',
            garage_number TEXT NOT NULL DEFAULT '',
            driver_name TEXT NOT NULL DEFAULT '',
            personnel_number TEXT NOT NULL DEFAULT '',
            departure_time TEXT,
            return_time TEXT,
            refueled_l REAL NOT NULL DEFAULT 0,
            fuel_name TEXT NOT NULL DEFAULT '',
            route TEXT NOT NULL DEFAULT '',
            assignment_text TEXT NOT NULL DEFAULT '',
            fuel_card_number TEXT NOT NULL DEFAULT '',
            source_pages_json TEXT NOT NULL DEFAULT '[]',
            confidence REAL NOT NULL DEFAULT 0,
            needs_review INTEGER NOT NULL DEFAULT 0,
            processing_status TEXT NOT NULL DEFAULT 'manual',
            folder_path TEXT NOT NULL DEFAULT '',
            individual_pdf_path TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(employee_id) REFERENCES work_employees(id) ON DELETE SET NULL,
            FOREIGN KEY(vehicle_id) REFERENCES garage_vehicles(id) ON DELETE SET NULL,
            FOREIGN KEY(source_document_id) REFERENCES work_documents(id) ON DELETE SET NULL
        )
        """
    )


def _rebuild_waybills(db: sqlite3.Connection) -> None:
    old_columns = {
        item["name"]
        for item in _table_columns(db, "garage_waybills")
    }
    temporary = "garage_waybills_migration_v2"
    db.execute(f"DROP TABLE IF EXISTS {temporary}")
    _create_waybill_table(db, temporary)

    defaults = {
        "batch_id": "NULL",
        "organization": "''",
        "department": "''",
        "vehicle_make": "''",
        "vehicle_model": "''",
        "vehicle_vin": "''",
        "garage_number": "''",
        "driver_name": "''",
        "personnel_number": "''",
        "departure_time": "NULL",
        "return_time": "NULL",
        "refueled_l": "0",
        "fuel_name": "''",
        "route": "''",
        "assignment_text": "''",
        "fuel_card_number": "''",
        "source_pages_json": "'[]'",
        "confidence": "0",
        "needs_review": "0",
        "processing_status": "'manual'",
        "folder_path": "''",
        "individual_pdf_path": "''",
    }
    select_expr = []
    for name in WAYBILL_COLUMNS:
        if name in old_columns:
            select_expr.append(name)
        elif name in defaults:
            select_expr.append(f"{defaults[name]} AS {name}")
        else:
            raise RuntimeError(f"missing migration expression for {name}")

    db.execute(
        f"""
        INSERT INTO {temporary}({", ".join(WAYBILL_COLUMNS)})
        SELECT {", ".join(select_expr)}
        FROM garage_waybills
        """
    )
    db.execute("DROP TABLE garage_waybills")
    db.execute(
        f"ALTER TABLE {temporary} RENAME TO garage_waybills"
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_garage_waybills_month
        ON garage_waybills(trip_date, vehicle_id, employee_id)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_garage_waybills_batch
        ON garage_waybills(batch_id, trip_date)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_garage_waybills_review
        ON garage_waybills(needs_review, processing_status, trip_date)
        """
    )


def apply_migrations(db: sqlite3.Connection) -> list[str]:
    """Apply narrow, idempotent SQLite migrations after schema bootstrap."""
    applied: list[str] = []
    if _needs_waybill_rebuild(db):
        db.execute("PRAGMA foreign_keys=OFF")
        try:
            _rebuild_waybills(db)
            db.execute(
                "INSERT OR REPLACE INTO system_meta(key, value) VALUES(?, ?)",
                ("migration.garage_waybills_v2", _now()),
            )
            db.commit()
            applied.append("garage_waybills_v2")
        finally:
            db.execute("PRAGMA foreign_keys=ON")
    return applied
