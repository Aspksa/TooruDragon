from __future__ import annotations

import base64
import re
from datetime import date, datetime, timezone
from uuid import uuid4

from core.system.database import Database
from core.work.legacy_xls import LegacyXlsWorkbook


CARD_RE = re.compile(r"Карта\s*№?\s*(\d{10,})", re.IGNORECASE)
PERIOD_RE = re.compile(
    r"Период\s+с\s+(\d{1,2}[.]\d{1,2}[.]\d{4})"
    r"\s+по\s+(\d{1,2}[.]\d{1,2}[.]\d{4})",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_date(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError("date must use YYYY-MM-DD or DD.MM.YYYY format")


def _month_bounds(month: str) -> tuple[str, str]:
    try:
        start = datetime.strptime(str(month), "%Y-%m").date().replace(day=1)
    except ValueError as exc:
        raise ValueError("month must use YYYY-MM format") from exc
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    end = date.fromordinal(next_month.toordinal() - 1)
    return start.isoformat(), end.isoformat()


def _float(value, field: str, *, allow_none: bool = False) -> float | None:
    if value is None or str(value).strip() == "":
        if allow_none:
            return None
        return 0.0
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if result < 0:
        raise ValueError(f"{field} cannot be negative")
    return round(result, 4)


def _card_number(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if digits and len(digits) < 10:
        raise ValueError("fuel card number is too short")
    return digits


def _fuel_kind(name: str) -> str:
    value = str(name or "").upper()
    if "ДИЗЕЛ" in value or "ДТ-" in value:
        return "diesel"
    for grade in ("98", "95", "92", "100"):
        if f"АИ-{grade}" in value or f"АИ {grade}" in value:
            return f"gasoline_{grade}"
    if "БЕНЗИН" in value:
        return "gasoline"
    return "other"


class GarageFuelService:
    def __init__(self, database: Database):
        self.db = database

    # Employees and fuel cards -------------------------------------------------

    def set_employee_fuel_card(
        self,
        employee_id: str,
        card_number: str,
        *,
        valid_from: str | None = None,
        source: str = "manual",
    ) -> dict:
        self._employee(employee_id)
        number = _card_number(card_number)
        if not number:
            raise ValueError("fuel card number is required")
        start = _iso_date(valid_from)
        existing_owner = self.db.query(
            """
            SELECT employee_id
            FROM work_employee_fuel_cards
            WHERE card_number=? AND active=1
            LIMIT 1
            """,
            (number,),
        )
        if existing_owner and existing_owner[0]["employee_id"] != employee_id:
            raise ValueError("fuel card is already assigned to another employee")

        current = self.db.query(
            """
            SELECT id, card_number
            FROM work_employee_fuel_cards
            WHERE employee_id=? AND active=1
            ORDER BY created_at DESC
            """,
            (employee_id,),
        )
        if current and start is None:
            start = date.today().isoformat()
        for item in current:
            if item["card_number"] == number:
                return self.employee_card(employee_id) or {}
            self.db.execute(
                """
                UPDATE work_employee_fuel_cards
                SET active=0, valid_to=?, updated_at=?
                WHERE id=?
                """,
                (start, _now(), item["id"]),
            )

        now = _now()
        self.db.execute(
            """
            INSERT INTO work_employee_fuel_cards(
                id, employee_id, card_number, valid_from, valid_to,
                active, source, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, NULL, 1, ?, ?, ?)
            """,
            (
                str(uuid4()),
                employee_id,
                number,
                start,
                str(source or "manual"),
                now,
                now,
            ),
        )
        self.reconcile_transactions()
        return self.employee_card(employee_id) or {}

    def employee_card(self, employee_id: str) -> dict | None:
        rows = self.db.query(
            """
            SELECT id, employee_id, card_number, valid_from, valid_to,
                   active, source, created_at, updated_at
            FROM work_employee_fuel_cards
            WHERE employee_id=? AND active=1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (employee_id,),
        )
        if not rows:
            return None
        item = dict(rows[0])
        item["active"] = bool(item["active"])
        return item

    def employee_directory(self) -> list[dict]:
        rows = self.db.query(
            """
            SELECT e.id, e.personnel_number, e.full_name, e.department,
                   e.position, e.active,
                   c.card_number AS fuel_card_number,
                   v.id AS vehicle_id,
                   v.registration_number,
                   v.make,
                   v.model
            FROM work_employees e
            LEFT JOIN work_employee_fuel_cards c
              ON c.employee_id=e.id AND c.active=1
            LEFT JOIN garage_driver_vehicle_assignments a
              ON a.employee_id=e.id AND a.active=1
            LEFT JOIN garage_vehicles v
              ON v.id=a.vehicle_id AND v.active=1
            ORDER BY e.department, e.full_name, e.personnel_number
            """
        )
        for item in rows:
            item["active"] = bool(item["active"])
        return rows

    # Vehicles and driver assignments -----------------------------------------

    def save_vehicle(self, payload: dict) -> dict:
        registration = re.sub(
            r"\s+",
            "",
            str(payload.get("registration_number") or "").upper(),
        )
        if not registration:
            raise ValueError("registration_number is required")
        vehicle_id = str(payload.get("id") or "").strip() or str(uuid4())
        vin = re.sub(r"\s+", "", str(payload.get("vin") or "").upper())
        make = str(payload.get("make") or "").strip()
        model = str(payload.get("model") or "").strip()
        department = str(payload.get("department") or "").strip()
        fuel_type = str(payload.get("fuel_type") or "").strip()
        tank_capacity = _float(
            payload.get("tank_capacity_l"),
            "tank_capacity_l",
            allow_none=True,
        )
        norm = _float(
            payload.get("default_norm_l_per_100km"),
            "default_norm_l_per_100km",
            allow_none=True,
        )
        active = bool(payload.get("active", True))
        now = _now()

        existing = self.db.query(
            "SELECT id FROM garage_vehicles WHERE id=?",
            (vehicle_id,),
        )
        if existing:
            self.db.execute(
                """
                UPDATE garage_vehicles
                SET registration_number=?, vin=?, make=?, model=?,
                    department=?, fuel_type=?, tank_capacity_l=?,
                    default_norm_l_per_100km=?, active=?, updated_at=?
                WHERE id=?
                """,
                (
                    registration,
                    vin,
                    make,
                    model,
                    department,
                    fuel_type,
                    tank_capacity,
                    norm,
                    1 if active else 0,
                    now,
                    vehicle_id,
                ),
            )
        else:
            self.db.execute(
                """
                INSERT INTO garage_vehicles(
                    id, registration_number, vin, make, model, department,
                    fuel_type, tank_capacity_l, default_norm_l_per_100km, active,
                    created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vehicle_id,
                    registration,
                    vin,
                    make,
                    model,
                    department,
                    fuel_type,
                    tank_capacity,
                    norm,
                    1 if active else 0,
                    now,
                    now,
                ),
            )
        return self.vehicle(vehicle_id)

    def vehicle(self, vehicle_id: str) -> dict:
        rows = self.db.query(
            """
            SELECT id, registration_number, vin, make, model, department,
                   fuel_type, tank_capacity_l, default_norm_l_per_100km, active,
                   created_at, updated_at
            FROM garage_vehicles
            WHERE id=?
            """,
            (vehicle_id,),
        )
        if not rows:
            raise KeyError(vehicle_id)
        item = dict(rows[0])
        item["active"] = bool(item["active"])
        return item

    def vehicles(self, *, active_only: bool = True) -> list[dict]:
        sql = """
            SELECT id, registration_number, vin, make, model, department,
                   fuel_type, tank_capacity_l, default_norm_l_per_100km, active,
                   created_at, updated_at
            FROM garage_vehicles
        """
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY registration_number, make, model"
        rows = self.db.query(sql)
        for item in rows:
            item["active"] = bool(item["active"])
        return rows

    def assign_driver_vehicle(
        self,
        employee_id: str,
        vehicle_id: str,
        *,
        valid_from: str | None = None,
        source: str = "manual",
        note: str = "",
    ) -> dict:
        self._employee(employee_id)
        self.vehicle(vehicle_id)
        start = _iso_date(valid_from)
        now = _now()

        current = self.db.query(
            """
            SELECT id, vehicle_id
            FROM garage_driver_vehicle_assignments
            WHERE employee_id=? AND active=1
            ORDER BY created_at DESC
            """,
            (employee_id,),
        )
        if current and start is None:
            start = date.today().isoformat()
        for item in current:
            if item["vehicle_id"] == vehicle_id:
                return self.driver_assignment(employee_id) or {}
            self.db.execute(
                """
                UPDATE garage_driver_vehicle_assignments
                SET active=0, valid_to=?, updated_at=?
                WHERE id=?
                """,
                (start, now, item["id"]),
            )

        assignment_id = str(uuid4())
        self.db.execute(
            """
            INSERT INTO garage_driver_vehicle_assignments(
                id, employee_id, vehicle_id, valid_from, valid_to,
                active, source, note, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, NULL, 1, ?, ?, ?, ?)
            """,
            (
                assignment_id,
                employee_id,
                vehicle_id,
                start,
                str(source or "manual"),
                str(note or ""),
                now,
                now,
            ),
        )
        self.reconcile_transactions()
        return self.driver_assignment(employee_id) or {}

    def driver_assignment(self, employee_id: str) -> dict | None:
        rows = self.db.query(
            """
            SELECT a.id, a.employee_id, a.vehicle_id, a.valid_from,
                   a.valid_to, a.active, a.source, a.note,
                   v.registration_number, v.make, v.model
            FROM garage_driver_vehicle_assignments a
            JOIN garage_vehicles v ON v.id=a.vehicle_id
            WHERE a.employee_id=? AND a.active=1
            ORDER BY a.created_at DESC
            LIMIT 1
            """,
            (employee_id,),
        )
        if not rows:
            return None
        item = dict(rows[0])
        item["active"] = bool(item["active"])
        return item

    # Waybills ----------------------------------------------------------------

    def save_waybill(self, payload: dict) -> dict:
        employee_id = str(payload.get("employee_id") or "").strip()
        if not employee_id:
            raise ValueError("employee_id is required")
        self._employee(employee_id)

        trip_date = _iso_date(payload.get("trip_date"))
        if not trip_date:
            raise ValueError("trip_date is required")

        vehicle_id = str(payload.get("vehicle_id") or "").strip()
        if not vehicle_id:
            vehicle_id = self._vehicle_for_driver(employee_id, trip_date) or ""
        if not vehicle_id:
            raise ValueError("vehicle_id is required or driver must have a vehicle")
        vehicle = self.vehicle(vehicle_id)

        odometer_start = _float(
            payload.get("odometer_start"),
            "odometer_start",
            allow_none=True,
        )
        odometer_end = _float(
            payload.get("odometer_end"),
            "odometer_end",
            allow_none=True,
        )
        if (
            odometer_start is not None
            and odometer_end is not None
            and odometer_end < odometer_start
        ):
            raise ValueError("odometer_end cannot be below odometer_start")

        supplied_distance = _float(
            payload.get("distance_km"),
            "distance_km",
            allow_none=True,
        )
        if supplied_distance is None:
            if odometer_start is not None and odometer_end is not None:
                distance = round(odometer_end - odometer_start, 2)
            else:
                distance = 0.0
        else:
            distance = supplied_distance

        fuel_open = _float(payload.get("fuel_open_l"), "fuel_open_l") or 0.0
        fuel_issued = _float(payload.get("fuel_issued_l"), "fuel_issued_l") or 0.0
        refueled = _float(payload.get("refueled_l"), "refueled_l") or 0.0
        fuel_close = _float(payload.get("fuel_close_l"), "fuel_close_l") or 0.0
        actual = round(fuel_open + fuel_issued + refueled - fuel_close, 4)
        if actual < -0.0001:
            raise ValueError("calculated fuel consumption cannot be negative")
        actual = max(0.0, actual)

        norm = _float(
            payload.get(
                "norm_l_per_100km",
                vehicle.get("default_norm_l_per_100km"),
            ),
            "norm_l_per_100km",
            allow_none=True,
        )
        norm_consumption = (
            round(distance * norm / 100.0, 4)
            if norm is not None
            else None
        )
        deviation = (
            round(actual - norm_consumption, 4)
            if norm_consumption is not None
            else None
        )

        waybill_id = str(payload.get("id") or "").strip() or str(uuid4())
        now = _now()
        values = (
            str(payload.get("waybill_number") or "").strip(),
            trip_date,
            employee_id,
            vehicle_id,
            odometer_start,
            odometer_end,
            distance,
            fuel_open,
            fuel_issued,
            fuel_close,
            refueled,
            norm,
            actual,
            norm_consumption,
            deviation,
            str(payload.get("source_document_id") or "").strip() or None,
            str(payload.get("note") or "").strip(),
            now,
        )
        existing = self.db.query(
            "SELECT id FROM garage_waybills WHERE id=?",
            (waybill_id,),
        )
        if existing:
            self.db.execute(
                """
                UPDATE garage_waybills
                SET waybill_number=?, trip_date=?, employee_id=?, vehicle_id=?,
                    odometer_start=?, odometer_end=?, distance_km=?,
                    fuel_open_l=?, fuel_issued_l=?, fuel_close_l=?,
                    refueled_l=?, norm_l_per_100km=?, actual_consumption_l=?,
                    norm_consumption_l=?, deviation_l=?, source_document_id=?,
                    note=?, updated_at=?
                WHERE id=?
                """,
                values + (waybill_id,),
            )
        else:
            self.db.execute(
                """
                INSERT INTO garage_waybills(
                    id, waybill_number, trip_date, employee_id, vehicle_id,
                    odometer_start, odometer_end, distance_km,
                    fuel_open_l, fuel_issued_l, fuel_close_l, refueled_l,
                    norm_l_per_100km, actual_consumption_l,
                    norm_consumption_l, deviation_l, source_document_id,
                    note, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (waybill_id,) + values[:-1] + (now, now),
            )
        return self.waybill(waybill_id)

    def waybill(self, waybill_id: str) -> dict:
        rows = self.db.query(
            """
            SELECT w.*, e.full_name, e.personnel_number,
                   v.registration_number, v.make, v.model
            FROM garage_waybills w
            LEFT JOIN work_employees e ON e.id=w.employee_id
            LEFT JOIN garage_vehicles v ON v.id=w.vehicle_id
            WHERE w.id=?
            """,
            (waybill_id,),
        )
        if not rows:
            raise KeyError(waybill_id)
        return dict(rows[0])

    def waybills(self, month: str) -> list[dict]:
        start, end = _month_bounds(month)
        return self.db.query(
            """
            SELECT w.*, e.full_name, e.personnel_number,
                   v.registration_number, v.make, v.model
            FROM garage_waybills w
            LEFT JOIN work_employees e ON e.id=w.employee_id
            LEFT JOIN garage_vehicles v ON v.id=w.vehicle_id
            WHERE w.trip_date BETWEEN ? AND ?
            ORDER BY w.trip_date DESC, w.waybill_number DESC
            """,
            (start, end),
        )

    # Fuel statement import ----------------------------------------------------

    @staticmethod
    def parse_statement_sheet(sheet) -> dict:
        cells = sheet.cells
        if not cells:
            raise ValueError("fuel statement sheet is empty")
        max_row = max(row for row, _ in cells)

        period_start = None
        period_end = None
        for value in cells.values():
            if isinstance(value, str):
                match = PERIOD_RE.search(value)
                if match:
                    period_start = _iso_date(match.group(1))
                    period_end = _iso_date(match.group(2))
                    break
        if not period_start or not period_end:
            raise ValueError("fuel statement period was not found")

        transactions = []
        cards = {}
        row = 0
        while row <= max_row:
            first = cells.get((row, 0))
            match = CARD_RE.search(first) if isinstance(first, str) else None
            if not match:
                row += 1
                continue

            card = match.group(1)
            holder_value = cells.get((row, 3))
            holder = (
                str(holder_value).strip()
                if isinstance(holder_value, str)
                and str(holder_value).strip()
                and str(holder_value).strip().lower() != "азс"
                else ""
            )
            cards[card] = holder

            scan = row + 1
            while scan <= max_row:
                next_first = cells.get((scan, 0))
                if (
                    isinstance(next_first, str)
                    and CARD_RE.search(next_first)
                ):
                    break

                raw_date = cells.get((scan, 1))
                quantity = cells.get((scan, 6))
                amount = cells.get((scan, 7))
                if (
                    isinstance(next_first, str)
                    and raw_date not in {None, ""}
                    and quantity not in {None, ""}
                    and amount not in {None, ""}
                ):
                    try:
                        operation_date = _iso_date(str(raw_date))
                        quantity_l = float(quantity)
                        amount_value = float(amount)
                    except (ValueError, TypeError):
                        operation_date = None
                    if operation_date:
                        price = cells.get((scan, 5))
                        transactions.append({
                            "source_row": scan + 1,
                            "card_number": card,
                            "holder_label": holder,
                            "operation": str(next_first).strip(),
                            "operation_date": operation_date,
                            "operation_time": str(cells.get((scan, 2)) or "").strip(),
                            "station": str(cells.get((scan, 3)) or "").strip(),
                            "fuel_name": str(cells.get((scan, 4)) or "").strip(),
                            "fuel_kind": _fuel_kind(cells.get((scan, 4)) or ""),
                            "price_per_liter": round(float(price or 0), 4),
                            "quantity_l": round(quantity_l, 4),
                            "amount": round(amount_value, 2),
                        })
                scan += 1

            row = scan

        if not transactions:
            raise ValueError("fuel statement contains no transaction rows")

        return {
            "period_start": period_start,
            "period_end": period_end,
            "cards": cards,
            "transactions": transactions,
            "card_count": len(cards),
            "transaction_count": len(transactions),
            "total_liters": round(
                sum(item["quantity_l"] for item in transactions),
                4,
            ),
            "total_amount": round(
                sum(item["amount"] for item in transactions),
                2,
            ),
        }

    def import_fuel_statement(
        self,
        *,
        document_id: str,
        original_name: str,
        content_base64: str,
    ) -> dict:
        existing = self.db.query(
            "SELECT id FROM garage_fuel_statements WHERE document_id=?",
            (document_id,),
        )
        if existing:
            return self.statement(existing[0]["id"])

        try:
            raw = base64.b64decode(content_base64, validate=True)
        except Exception as exc:
            raise ValueError("invalid base64 fuel statement") from exc

        workbook = LegacyXlsWorkbook(raw)
        parsed = self.parse_statement_sheet(workbook.first_sheet())
        statement_id = str(uuid4())
        now = _now()
        self.db.execute(
            """
            INSERT INTO garage_fuel_statements(
                id, document_id, original_name, period_start, period_end,
                card_count, transaction_count, total_liters, total_amount,
                parser, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                statement_id,
                document_id,
                str(original_name or ""),
                parsed["period_start"],
                parsed["period_end"],
                parsed["card_count"],
                parsed["transaction_count"],
                parsed["total_liters"],
                parsed["total_amount"],
                "builtin_ole_biff5",
                now,
                now,
            ),
        )

        with self.db.connect() as db:
            for item in parsed["transactions"]:
                employee_id = self._employee_for_card(
                    item["card_number"],
                    item["operation_date"],
                )
                vehicle_id = (
                    self._vehicle_for_driver(
                        employee_id,
                        item["operation_date"],
                    )
                    if employee_id
                    else None
                )
                if not employee_id:
                    resolution = "card_unassigned"
                elif not vehicle_id:
                    resolution = "driver_no_vehicle"
                else:
                    resolution = "linked"

                db.execute(
                    """
                    INSERT INTO garage_fuel_transactions(
                        id, statement_id, document_id, source_row,
                        card_number, holder_label, employee_id, vehicle_id,
                        operation, operation_date, operation_time, station,
                        fuel_name, fuel_kind, price_per_liter, quantity_l,
                        amount, resolution_status, created_at, updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        statement_id,
                        document_id,
                        item["source_row"],
                        item["card_number"],
                        item["holder_label"],
                        employee_id,
                        vehicle_id,
                        item["operation"],
                        item["operation_date"],
                        item["operation_time"],
                        item["station"],
                        item["fuel_name"],
                        item["fuel_kind"],
                        item["price_per_liter"],
                        item["quantity_l"],
                        item["amount"],
                        resolution,
                        now,
                        now,
                    ),
                )
        return self.statement(statement_id)

    def statement(self, statement_id: str) -> dict:
        rows = self.db.query(
            """
            SELECT *
            FROM garage_fuel_statements
            WHERE id=?
            """,
            (statement_id,),
        )
        if not rows:
            raise KeyError(statement_id)
        item = dict(rows[0])
        counts = self.db.query(
            """
            SELECT resolution_status, COUNT(*) AS count
            FROM garage_fuel_transactions
            WHERE statement_id=?
            GROUP BY resolution_status
            """,
            (statement_id,),
        )
        item["resolution"] = {
            row["resolution_status"]: row["count"]
            for row in counts
        }
        return item

    def statements(self, limit: int = 50) -> list[dict]:
        rows = self.db.query(
            """
            SELECT s.*,
                   SUM(CASE WHEN t.resolution_status='linked' THEN 1 ELSE 0 END)
                       AS linked_transactions,
                   SUM(CASE WHEN t.resolution_status!='linked' THEN 1 ELSE 0 END)
                       AS unresolved_transactions
            FROM garage_fuel_statements s
            LEFT JOIN garage_fuel_transactions t ON t.statement_id=s.id
            GROUP BY s.id
            ORDER BY s.period_start DESC, s.created_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 200)),),
        )
        return rows

    def unresolved_cards(self, month: str | None = None) -> list[dict]:
        clauses = ["t.resolution_status!='linked'"]
        params: list = []
        if month:
            start, end = _month_bounds(month)
            clauses.append("t.operation_date BETWEEN ? AND ?")
            params.extend([start, end])
        return self.db.query(
            f"""
            SELECT t.card_number,
                   MAX(t.holder_label) AS holder_label,
                   t.resolution_status,
                   t.employee_id,
                   MAX(e.full_name) AS full_name,
                   COUNT(*) AS transactions,
                   ROUND(SUM(t.quantity_l), 4) AS liters,
                   ROUND(SUM(t.amount), 2) AS amount,
                   MIN(t.operation_date) AS first_date,
                   MAX(t.operation_date) AS last_date
            FROM garage_fuel_transactions t
            LEFT JOIN work_employees e ON e.id=t.employee_id
            WHERE {' AND '.join(clauses)}
            GROUP BY t.card_number, t.resolution_status, t.employee_id
            ORDER BY amount DESC, t.card_number
            """,
            tuple(params),
        )

    def reconcile_transactions(self) -> dict:
        rows = self.db.query(
            """
            SELECT id, card_number, operation_date
            FROM garage_fuel_transactions
            WHERE resolution_status!='linked'
            ORDER BY operation_date, id
            """
        )
        linked = 0
        now = _now()
        for item in rows:
            employee_id = self._employee_for_card(
                item["card_number"],
                item["operation_date"],
            )
            vehicle_id = (
                self._vehicle_for_driver(employee_id, item["operation_date"])
                if employee_id
                else None
            )
            if not employee_id:
                status = "card_unassigned"
            elif not vehicle_id:
                status = "driver_no_vehicle"
            else:
                status = "linked"
                linked += 1
            self.db.execute(
                """
                UPDATE garage_fuel_transactions
                SET employee_id=?, vehicle_id=?, resolution_status=?, updated_at=?
                WHERE id=?
                """,
                (
                    employee_id,
                    vehicle_id,
                    status,
                    now,
                    item["id"],
                ),
            )
        return {"checked": len(rows), "linked": linked}

    # Analytics ---------------------------------------------------------------

    def monthly_summary(self, month: str) -> dict:
        start, end = _month_bounds(month)
        statement_totals = self.db.query(
            """
            SELECT
                COUNT(*) AS transactions,
                ROUND(COALESCE(SUM(quantity_l), 0), 4) AS liters,
                ROUND(COALESCE(SUM(amount), 0), 2) AS amount,
                SUM(CASE WHEN resolution_status!='linked' THEN 1 ELSE 0 END)
                    AS unresolved
            FROM garage_fuel_transactions
            WHERE operation_date BETWEEN ? AND ?
            """,
            (start, end),
        )[0]
        waybill_totals = self.db.query(
            """
            SELECT
                COUNT(*) AS waybills,
                ROUND(COALESCE(SUM(distance_km), 0), 2) AS distance_km,
                ROUND(COALESCE(SUM(fuel_issued_l), 0), 4) AS issued_l,
                ROUND(COALESCE(SUM(actual_consumption_l), 0), 4) AS consumption_l,
                ROUND(COALESCE(SUM(norm_consumption_l), 0), 4) AS norm_l,
                ROUND(COALESCE(SUM(deviation_l), 0), 4) AS deviation_l
            FROM garage_waybills
            WHERE trip_date BETWEEN ? AND ?
              AND COALESCE(needs_review, 0)=0
            """,
            (start, end),
        )[0]

        statement_rows = self.db.query(
            """
            SELECT t.vehicle_id, t.employee_id,
                   ROUND(SUM(t.quantity_l), 4) AS statement_liters,
                   ROUND(SUM(t.amount), 2) AS statement_amount
            FROM garage_fuel_transactions t
            WHERE t.operation_date BETWEEN ? AND ?
              AND t.vehicle_id IS NOT NULL
            GROUP BY t.vehicle_id, t.employee_id
            """,
            (start, end),
        )
        waybill_rows = self.db.query(
            """
            SELECT w.vehicle_id, w.employee_id,
                   ROUND(SUM(w.distance_km), 2) AS distance_km,
                   ROUND(SUM(w.fuel_issued_l), 4) AS waybill_issued_liters,
                   ROUND(SUM(w.actual_consumption_l), 4) AS consumption_liters,
                   ROUND(SUM(COALESCE(w.norm_consumption_l, 0)), 4) AS norm_liters,
                   ROUND(SUM(COALESCE(w.deviation_l, 0)), 4) AS deviation_liters,
                   COUNT(*) AS waybills
            FROM garage_waybills w
            WHERE w.trip_date BETWEEN ? AND ?
              AND COALESCE(w.needs_review, 0)=0
              AND w.vehicle_id IS NOT NULL
              AND w.employee_id IS NOT NULL
            GROUP BY w.vehicle_id, w.employee_id
            """,
            (start, end),
        )

        combined: dict[tuple[str, str], dict] = {}
        for row in statement_rows:
            key = (row["vehicle_id"], row["employee_id"])
            combined[key] = {
                "vehicle_id": row["vehicle_id"],
                "employee_id": row["employee_id"],
                "statement_liters": float(row["statement_liters"] or 0),
                "statement_amount": float(row["statement_amount"] or 0),
                "distance_km": 0.0,
                "waybill_issued_liters": 0.0,
                "consumption_liters": 0.0,
                "norm_liters": 0.0,
                "deviation_liters": 0.0,
                "waybills": 0,
            }
        for row in waybill_rows:
            key = (row["vehicle_id"], row["employee_id"])
            item = combined.setdefault(key, {
                "vehicle_id": row["vehicle_id"],
                "employee_id": row["employee_id"],
                "statement_liters": 0.0,
                "statement_amount": 0.0,
                "distance_km": 0.0,
                "waybill_issued_liters": 0.0,
                "consumption_liters": 0.0,
                "norm_liters": 0.0,
                "deviation_liters": 0.0,
                "waybills": 0,
            })
            for field in (
                "distance_km",
                "waybill_issued_liters",
                "consumption_liters",
                "norm_liters",
                "deviation_liters",
            ):
                item[field] = float(row[field] or 0)
            item["waybills"] = int(row["waybills"] or 0)

        rows = []
        for item in combined.values():
            employee = self._employee(item["employee_id"])
            vehicle = self.vehicle(item["vehicle_id"])
            item["full_name"] = employee["full_name"]
            item["personnel_number"] = employee["personnel_number"]
            item["registration_number"] = vehicle["registration_number"]
            item["vehicle_name"] = " ".join(
                part for part in (vehicle["make"], vehicle["model"]) if part
            )
            item["statement_vs_waybill_liters"] = round(
                item["statement_liters"] - item["waybill_issued_liters"],
                4,
            )
            rows.append(item)

        rows.sort(key=lambda item: (
            item["registration_number"],
            item["full_name"],
        ))
        return {
            "month": month,
            "statement": dict(statement_totals),
            "waybills": dict(waybill_totals),
            "rows": rows,
            "unresolved_cards": self.unresolved_cards(month),
        }

    def stats(self) -> dict:
        vehicles = self.db.query(
            "SELECT COUNT(*) AS count FROM garage_vehicles WHERE active=1"
        )[0]["count"]
        cards = self.db.query(
            "SELECT COUNT(*) AS count FROM work_employee_fuel_cards WHERE active=1"
        )[0]["count"]
        unresolved = self.db.query(
            """
            SELECT COUNT(*) AS count
            FROM garage_fuel_transactions
            WHERE resolution_status!='linked'
            """
        )[0]["count"]
        statements = self.db.query(
            "SELECT COUNT(*) AS count FROM garage_fuel_statements"
        )[0]["count"]
        return {
            "vehicles": int(vehicles or 0),
            "active_fuel_cards": int(cards or 0),
            "fuel_statements": int(statements or 0),
            "unresolved_transactions": int(unresolved or 0),
        }

    # Resolution helpers ------------------------------------------------------

    def _employee(self, employee_id: str) -> dict:
        rows = self.db.query(
            """
            SELECT id, personnel_number, full_name, department,
                   position, active
            FROM work_employees
            WHERE id=?
            """,
            (employee_id,),
        )
        if not rows:
            raise KeyError(employee_id)
        item = dict(rows[0])
        item["active"] = bool(item["active"])
        return item

    def _employee_for_card(
        self,
        card_number: str,
        operation_date: str,
    ) -> str | None:
        rows = self.db.query(
            """
            SELECT employee_id
            FROM work_employee_fuel_cards
            WHERE card_number=?
              AND (valid_from IS NULL OR valid_from<=?)
              AND (valid_to IS NULL OR valid_to>=?)
            ORDER BY active DESC, COALESCE(valid_from, '') DESC, created_at DESC
            LIMIT 1
            """,
            (card_number, operation_date, operation_date),
        )
        return rows[0]["employee_id"] if rows else None

    def _vehicle_for_driver(
        self,
        employee_id: str | None,
        operation_date: str,
    ) -> str | None:
        if not employee_id:
            return None
        rows = self.db.query(
            """
            SELECT vehicle_id
            FROM garage_driver_vehicle_assignments
            WHERE employee_id=?
              AND (valid_from IS NULL OR valid_from<=?)
              AND (valid_to IS NULL OR valid_to>=?)
            ORDER BY active DESC, COALESCE(valid_from, '') DESC, created_at DESC
            LIMIT 1
            """,
            (employee_id, operation_date, operation_date),
        )
        return rows[0]["vehicle_id"] if rows else None
