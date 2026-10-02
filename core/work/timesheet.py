from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import uuid4

from core.system.database import Database


STATUS_CODES = {
    "work": "Я",
    "remote": "УД",
    "vacation": "ОТ",
    "sick": "Б",
    "day_off": "В",
    "business_trip": "К",
    "absence": "НН",
    "training": "ПК",
}

WORKING_STATUSES = {"work", "remote", "business_trip", "training"}
NON_WORKING_STATUSES = {"vacation", "sick", "day_off", "absence"}
CUSTOM_VALUE_TYPES = {"text", "number", "checkbox"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _month_bounds(month: str) -> tuple[date, date]:
    try:
        year_text, month_text = str(month).split("-", 1)
        year = int(year_text)
        month_number = int(month_text)
        start = date(year, month_number, 1)
    except (ValueError, TypeError):
        raise ValueError("month must use YYYY-MM format")
    last = calendar.monthrange(year, month_number)[1]
    return start, date(year, month_number, last)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise ValueError("work_date must use YYYY-MM-DD format")


def _hours(value, *, field: str, maximum: float = 24.0) -> float:
    try:
        result = float(value or 0)
    except (ValueError, TypeError):
        raise ValueError(f"{field} must be numeric")
    if result < 0 or result > maximum:
        raise ValueError(f"{field} must be between 0 and {maximum:g}")
    return round(result, 2)


@dataclass(frozen=True)
class MonthContext:
    month: str
    start: date
    end: date


class TimesheetService:
    def __init__(self, database: Database):
        self.db = database

    def save_employee(self, payload: dict) -> dict:
        full_name = str(payload.get("full_name", "")).strip()
        personnel_number = str(payload.get("personnel_number", "")).strip()
        if not full_name:
            raise ValueError("full_name is required")
        if not personnel_number:
            raise ValueError("personnel_number is required")

        employee_id = str(payload.get("id") or "").strip() or str(uuid4())
        department = str(payload.get("department", "")).strip()
        position = str(payload.get("position", "")).strip()
        schedule_type = str(payload.get("schedule_type", "5/2")).strip() or "5/2"
        weekly_hours = _hours(
            payload.get("weekly_hours", 40),
            field="weekly_hours",
            maximum=168,
        )
        active = _as_bool(payload.get("active", True))
        now = _now()

        existing = self.db.query(
            "SELECT id FROM work_employees WHERE id=?",
            (employee_id,),
        )
        if existing:
            self.db.execute(
                """
                UPDATE work_employees
                SET personnel_number=?, full_name=?, department=?, position=?,
                    schedule_type=?, weekly_hours=?, active=?, updated_at=?
                WHERE id=?
                """,
                (
                    personnel_number,
                    full_name,
                    department,
                    position,
                    schedule_type,
                    weekly_hours,
                    1 if active else 0,
                    now,
                    employee_id,
                ),
            )
        else:
            self.db.execute(
                """
                INSERT INTO work_employees(
                    id, personnel_number, full_name, department, position,
                    schedule_type, weekly_hours, active, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    personnel_number,
                    full_name,
                    department,
                    position,
                    schedule_type,
                    weekly_hours,
                    1 if active else 0,
                    now,
                    now,
                ),
            )

        return self.employee(employee_id)

    def employee(self, employee_id: str) -> dict:
        rows = self.db.query(
            """
            SELECT id, personnel_number, full_name, department, position,
                   schedule_type, weekly_hours, active, created_at, updated_at
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

    def employees(self, *, active_only: bool = False) -> list[dict]:
        sql = """
            SELECT id, personnel_number, full_name, department, position,
                   schedule_type, weekly_hours, active, created_at, updated_at
            FROM work_employees
        """
        params: tuple = ()
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY department, full_name, personnel_number"
        rows = self.db.query(sql, params)
        for item in rows:
            item["active"] = bool(item["active"])
        return rows

    def save_custom_column(self, payload: dict) -> dict:
        label = str(payload.get("label", "")).strip()
        if not label:
            raise ValueError("label is required")
        value_type = str(payload.get("value_type", "text")).strip().lower()
        if value_type not in CUSTOM_VALUE_TYPES:
            raise ValueError(
                "value_type must be one of: " + ", ".join(sorted(CUSTOM_VALUE_TYPES))
            )

        column_id = str(payload.get("id") or "").strip() or str(uuid4())
        key = str(payload.get("key") or "").strip() or f"field_{column_id[:8]}"
        sort_order = int(payload.get("sort_order", 100))
        active = _as_bool(payload.get("active", True))
        now = _now()

        existing = self.db.query(
            "SELECT id FROM work_timesheet_custom_columns WHERE id=?",
            (column_id,),
        )
        if existing:
            self.db.execute(
                """
                UPDATE work_timesheet_custom_columns
                SET key=?, label=?, value_type=?, sort_order=?, active=?, updated_at=?
                WHERE id=?
                """,
                (
                    key,
                    label,
                    value_type,
                    sort_order,
                    1 if active else 0,
                    now,
                    column_id,
                ),
            )
        else:
            self.db.execute(
                """
                INSERT INTO work_timesheet_custom_columns(
                    id, key, label, value_type, sort_order, active,
                    created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    column_id,
                    key,
                    label,
                    value_type,
                    sort_order,
                    1 if active else 0,
                    now,
                    now,
                ),
            )
        return self.custom_column(column_id)

    def custom_column(self, column_id: str) -> dict:
        rows = self.db.query(
            """
            SELECT id, key, label, value_type, sort_order, active,
                   created_at, updated_at
            FROM work_timesheet_custom_columns
            WHERE id=?
            """,
            (column_id,),
        )
        if not rows:
            raise KeyError(column_id)
        item = dict(rows[0])
        item["active"] = bool(item["active"])
        return item

    def custom_columns(self, *, active_only: bool = True) -> list[dict]:
        sql = """
            SELECT id, key, label, value_type, sort_order, active,
                   created_at, updated_at
            FROM work_timesheet_custom_columns
        """
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY sort_order, label, key"
        rows = self.db.query(sql)
        for item in rows:
            item["active"] = bool(item["active"])
        return rows

    def save_entry(self, payload: dict) -> dict:
        employee_id = str(payload.get("employee_id", "")).strip()
        if not employee_id:
            raise ValueError("employee_id is required")
        self.employee(employee_id)

        work_date = _date(payload.get("work_date"))
        status = str(payload.get("status", "work")).strip().lower() or "work"
        if status not in STATUS_CODES:
            raise ValueError(
                "status must be one of: " + ", ".join(sorted(STATUS_CODES))
            )

        planned_default = self.default_planned_hours(employee_id, work_date)
        planned = _hours(
            payload.get("planned_hours", planned_default),
            field="planned_hours",
        )
        actual = _hours(payload.get("actual_hours", 0), field="actual_hours")
        overtime = _hours(
            payload.get("overtime_hours", max(0, actual - planned)),
            field="overtime_hours",
            maximum=24,
        )
        night = _hours(
            payload.get("night_hours", 0),
            field="night_hours",
            maximum=24,
        )
        if night > actual:
            raise ValueError("night_hours cannot exceed actual_hours")

        note = str(payload.get("note", "")).strip()
        source = str(payload.get("source", "manual")).strip() or "manual"
        now = _now()

        existing = self.db.query(
            """
            SELECT id
            FROM work_timesheet_entries
            WHERE employee_id=? AND work_date=?
            """,
            (employee_id, work_date.isoformat()),
        )
        if existing:
            entry_id = existing[0]["id"]
            self.db.execute(
                """
                UPDATE work_timesheet_entries
                SET status=?, planned_hours=?, actual_hours=?, overtime_hours=?,
                    night_hours=?, note=?, source=?, updated_at=?
                WHERE id=?
                """,
                (
                    status,
                    planned,
                    actual,
                    overtime,
                    night,
                    note,
                    source,
                    now,
                    entry_id,
                ),
            )
        else:
            entry_id = str(uuid4())
            self.db.execute(
                """
                INSERT INTO work_timesheet_entries(
                    id, employee_id, work_date, status, planned_hours,
                    actual_hours, overtime_hours, night_hours, note, source,
                    created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    employee_id,
                    work_date.isoformat(),
                    status,
                    planned,
                    actual,
                    overtime,
                    night,
                    note,
                    source,
                    now,
                    now,
                ),
            )

        if "custom_values" in payload:
            self._save_custom_values(
                entry_id,
                payload.get("custom_values"),
            )

        return self.entry(entry_id)

    def entry(self, entry_id: str) -> dict:
        rows = self.db.query(
            """
            SELECT e.id, e.employee_id, e.work_date, e.status,
                   e.planned_hours, e.actual_hours, e.overtime_hours,
                   e.night_hours, e.note, e.source, e.created_at, e.updated_at,
                   p.personnel_number, p.full_name, p.department, p.position
            FROM work_timesheet_entries e
            JOIN work_employees p ON p.id=e.employee_id
            WHERE e.id=?
            """,
            (entry_id,),
        )
        if not rows:
            raise KeyError(entry_id)
        item = self._decorate_entry(dict(rows[0]))
        self._attach_custom_values([item])
        return item

    def entries(
        self,
        month: str,
        *,
        employee_id: str | None = None,
    ) -> list[dict]:
        ctx = self.month_context(month)
        clauses = ["e.work_date>=?", "e.work_date<=?"]
        params: list = [ctx.start.isoformat(), ctx.end.isoformat()]
        if employee_id:
            clauses.append("e.employee_id=?")
            params.append(employee_id)

        rows = self.db.query(
            f"""
            SELECT e.id, e.employee_id, e.work_date, e.status,
                   e.planned_hours, e.actual_hours, e.overtime_hours,
                   e.night_hours, e.note, e.source, e.created_at, e.updated_at,
                   p.personnel_number, p.full_name, p.department, p.position
            FROM work_timesheet_entries e
            JOIN work_employees p ON p.id=e.employee_id
            WHERE {' AND '.join(clauses)}
            ORDER BY p.full_name, e.work_date
            """,
            tuple(params),
        )
        items = [self._decorate_entry(dict(item)) for item in rows]
        self._attach_custom_values(items)
        return items

    def calendar(
        self,
        month: str,
        *,
        employee_id: str | None = None,
    ) -> dict:
        ctx = self.month_context(month)
        employees = (
            [self.employee(employee_id)]
            if employee_id
            else self.employees(active_only=True)
        )
        entries = self.entries(month, employee_id=employee_id)
        by_key = {
            (item["employee_id"], item["work_date"]): item
            for item in entries
        }

        days = []
        current = ctx.start
        while current <= ctx.end:
            days.append({
                "date": current.isoformat(),
                "day": current.day,
                "weekday": current.weekday(),
                "weekend": current.weekday() >= 5,
            })
            current = date.fromordinal(current.toordinal() + 1)

        rows = []
        for employee in employees:
            cells = []
            for day in days:
                key = (employee["id"], day["date"])
                entry = by_key.get(key)
                default_plan = self.default_planned_hours(
                    employee["id"],
                    date.fromisoformat(day["date"]),
                )
                cells.append({
                    "date": day["date"],
                    "weekend": day["weekend"],
                    "planned_default": default_plan,
                    "entry": entry,
                    "missing": (
                        entry is None
                        and default_plan > 0
                        and self._should_expect_entry(
                            date.fromisoformat(day["date"])
                        )
                    ),
                })
            rows.append({"employee": employee, "days": cells})

        return {
            "month": month,
            "days": days,
            "rows": rows,
            "status_codes": STATUS_CODES,
        }

    def summary(self, month: str) -> dict:
        ctx = self.month_context(month)
        employees = self.employees(active_only=True)
        entries = self.entries(month)
        grouped: dict[str, list[dict]] = {}
        for item in entries:
            grouped.setdefault(item["employee_id"], []).append(item)

        people = []
        totals = {
            "employees": len(employees),
            "planned_hours": 0.0,
            "actual_hours": 0.0,
            "overtime_hours": 0.0,
            "night_hours": 0.0,
            "missing_days": 0,
            "anomalies": 0,
        }

        for employee in employees:
            items = grouped.get(employee["id"], [])
            summary = self._employee_summary(ctx, employee, items)
            people.append(summary)
            totals["planned_hours"] += summary["planned_norm_hours"]
            for key in (
                "actual_hours",
                "overtime_hours",
                "night_hours",
            ):
                totals[key] += summary[key]
            totals["missing_days"] += summary["missing_days"]
            totals["anomalies"] += len(summary["anomalies"])

        for key in (
            "planned_hours",
            "actual_hours",
            "overtime_hours",
            "night_hours",
        ):
            totals[key] = round(totals[key], 2)

        return {
            "month": month,
            "totals": totals,
            "employees": people,
            "status_codes": STATUS_CODES,
        }

    def overtime_report(self, month: str) -> dict:
        ctx = self.month_context(month)
        employees = self.employees(active_only=True)
        entries = self.entries(month)
        grouped: dict[str, list[dict]] = {}
        for item in entries:
            grouped.setdefault(item["employee_id"], []).append(item)

        totals = {
            "employees": len(employees),
            "norm_hours": 0.0,
            "actual_hours": 0.0,
            "declared_overtime_hours": 0.0,
            "daily_excess_hours": 0.0,
            "month_excess_hours": 0.0,
            "deficit_hours": 0.0,
            "weekend_hours": 0.0,
            "night_hours": 0.0,
        }
        people = []

        for employee in employees:
            items = grouped.get(employee["id"], [])
            base = self._employee_summary(ctx, employee, items)
            daily_excess = round(
                sum(
                    max(
                        0.0,
                        float(item["actual_hours"]) - float(item["planned_hours"]),
                    )
                    for item in items
                    if item["status"] in WORKING_STATUSES
                ),
                2,
            )
            weekend_hours = round(
                sum(
                    float(item["actual_hours"])
                    for item in items
                    if item["weekend"]
                ),
                2,
            )
            month_excess = round(max(0.0, base["balance_hours"]), 2)
            deficit = round(max(0.0, -base["balance_hours"]), 2)
            declared = round(float(base["overtime_hours"]), 2)

            row = {
                "employee": employee,
                "norm_hours": base["planned_norm_hours"],
                "actual_hours": base["actual_hours"],
                "balance_hours": base["balance_hours"],
                "declared_overtime_hours": declared,
                "daily_excess_hours": daily_excess,
                "month_excess_hours": month_excess,
                "deficit_hours": deficit,
                "weekend_hours": weekend_hours,
                "night_hours": base["night_hours"],
            }
            people.append(row)
            for key in totals:
                if key == "employees":
                    continue
                totals[key] += float(row[key])

        for key in totals:
            if key != "employees":
                totals[key] = round(float(totals[key]), 2)

        return {
            "month": month,
            "totals": totals,
            "employees": people,
            "calculation_basis": {
                "declared_overtime_hours": (
                    "Сумма поля «Сверхурочно» из записей табеля."
                ),
                "daily_excess_hours": (
                    "Сумма положительного превышения факта над планом по рабочим дням."
                ),
                "month_excess_hours": (
                    "Положительная разница фактических часов и месячной нормы."
                ),
                "weekend_hours": (
                    "Фактические часы в календарные субботу и воскресенье."
                ),
                "note": (
                    "Это учётная аналитика табеля. Она не рассчитывает оплату, "
                    "коэффициенты или юридическую квалификацию сверхурочной работы."
                ),
            },
        }

    def anomalies(self, month: str) -> list[dict]:
        result = []
        for employee in self.summary(month)["employees"]:
            for anomaly in employee["anomalies"]:
                result.append({
                    "employee_id": employee["employee"]["id"],
                    "personnel_number": employee["employee"]["personnel_number"],
                    "full_name": employee["employee"]["full_name"],
                    **anomaly,
                })
        return result

    def default_planned_hours(self, employee_id: str, work_date: date) -> float:
        employee = self.employee(employee_id)
        if employee["schedule_type"] == "5/2":
            if work_date.weekday() >= 5:
                return 0.0
            return round(float(employee["weekly_hours"]) / 5.0, 2)
        return 0.0

    @staticmethod
    def month_context(month: str) -> MonthContext:
        start, end = _month_bounds(month)
        return MonthContext(month=month, start=start, end=end)

    def _save_custom_values(self, entry_id: str, values) -> None:
        if values is None:
            return
        if not isinstance(values, dict):
            raise ValueError("custom_values must be an object")

        columns = {
            item["id"]: item
            for item in self.custom_columns(active_only=False)
        }
        now = _now()
        with self.db.connect() as db:
            for column_id, raw_value in values.items():
                column_id = str(column_id)
                column = columns.get(column_id)
                if column is None:
                    raise ValueError(f"unknown custom column: {column_id}")

                if raw_value is None:
                    value_text = ""
                elif column["value_type"] == "checkbox":
                    value_text = "1" if _as_bool(raw_value) else "0"
                elif column["value_type"] == "number":
                    try:
                        value_text = str(round(float(raw_value), 4))
                    except (TypeError, ValueError):
                        raise ValueError(
                            f"custom field {column['label']} must be numeric"
                        )
                else:
                    value_text = str(raw_value).strip()

                db.execute(
                    """
                    INSERT INTO work_timesheet_custom_values(
                        entry_id, column_id, value_text, updated_at
                    )
                    VALUES(?, ?, ?, ?)
                    ON CONFLICT(entry_id, column_id) DO UPDATE SET
                        value_text=excluded.value_text,
                        updated_at=excluded.updated_at
                    """,
                    (entry_id, column_id, value_text, now),
                )

    def _attach_custom_values(self, items: list[dict]) -> None:
        if not items:
            return
        entry_ids = [item["id"] for item in items]
        placeholders = ",".join("?" for _ in entry_ids)
        rows = self.db.query(
            f"""
            SELECT v.entry_id, v.column_id, v.value_text,
                   c.key, c.label, c.value_type, c.sort_order
            FROM work_timesheet_custom_values v
            JOIN work_timesheet_custom_columns c ON c.id=v.column_id
            WHERE v.entry_id IN ({placeholders})
            ORDER BY c.sort_order, c.label
            """,
            tuple(entry_ids),
        )
        grouped: dict[str, dict] = {entry_id: {} for entry_id in entry_ids}
        for row in rows:
            value = row["value_text"]
            if row["value_type"] == "checkbox":
                value = value == "1"
            elif row["value_type"] == "number" and value != "":
                try:
                    value = float(value)
                except ValueError:
                    pass
            grouped[row["entry_id"]][row["column_id"]] = {
                "column_id": row["column_id"],
                "key": row["key"],
                "label": row["label"],
                "value_type": row["value_type"],
                "value": value,
            }

        for item in items:
            item["custom_values"] = grouped.get(item["id"], {})

    @staticmethod
    def _decorate_entry(item: dict) -> dict:
        item["status_code"] = STATUS_CODES.get(item["status"], item["status"])
        item["weekend"] = date.fromisoformat(item["work_date"]).weekday() >= 5
        return item

    @staticmethod
    def _should_expect_entry(work_date: date) -> bool:
        today = date.today()
        return work_date <= today

    def _employee_summary(
        self,
        ctx: MonthContext,
        employee: dict,
        entries: list[dict],
    ) -> dict:
        by_date = {item["work_date"]: item for item in entries}
        planned_norm = 0.0
        missing_days = 0

        current = ctx.start
        while current <= ctx.end:
            planned = self.default_planned_hours(employee["id"], current)
            planned_norm += planned
            if (
                planned > 0
                and current.isoformat() not in by_date
                and self._should_expect_entry(current)
            ):
                missing_days += 1
            current = date.fromordinal(current.toordinal() + 1)

        actual = round(sum(float(item["actual_hours"]) for item in entries), 2)
        overtime = round(
            sum(float(item["overtime_hours"]) for item in entries),
            2,
        )
        night = round(sum(float(item["night_hours"]) for item in entries), 2)
        recorded_plan = round(
            sum(float(item["planned_hours"]) for item in entries),
            2,
        )
        status_days = {
            status: sum(1 for item in entries if item["status"] == status)
            for status in STATUS_CODES
        }

        anomalies = []
        for item in entries:
            anomalies.extend(self._entry_anomalies(item))
        if missing_days:
            anomalies.append({
                "type": "missing_entries",
                "severity": "warning",
                "message": f"Нет записей за {missing_days} плановых дней",
                "count": missing_days,
            })

        return {
            "employee": employee,
            "planned_norm_hours": round(planned_norm, 2),
            "planned_hours": recorded_plan,
            "actual_hours": actual,
            "overtime_hours": overtime,
            "night_hours": night,
            "balance_hours": round(actual - planned_norm, 2),
            "missing_days": missing_days,
            "status_days": status_days,
            "anomalies": anomalies,
        }

    @staticmethod
    def _entry_anomalies(item: dict) -> list[dict]:
        result = []
        actual = float(item["actual_hours"])
        planned = float(item["planned_hours"])
        overtime = float(item["overtime_hours"])
        status = item["status"]

        if actual > 12:
            result.append({
                "type": "long_shift",
                "severity": "warning",
                "date": item["work_date"],
                "entry_id": item["id"],
                "message": f"Смена {actual:g} ч — требуется проверка",
            })
        if overtime > 4:
            result.append({
                "type": "high_overtime",
                "severity": "warning",
                "date": item["work_date"],
                "entry_id": item["id"],
                "message": f"Сверхурочные {overtime:g} ч — требуется проверка",
            })
        if item["weekend"] and actual > 0:
            result.append({
                "type": "weekend_work",
                "severity": "info",
                "date": item["work_date"],
                "entry_id": item["id"],
                "message": "Работа в выходной день",
            })
        if status in NON_WORKING_STATUSES and actual > 0:
            result.append({
                "type": "hours_on_nonworking_status",
                "severity": "error",
                "date": item["work_date"],
                "entry_id": item["id"],
                "message": (
                    f"Статус {STATUS_CODES.get(status, status)} содержит "
                    f"{actual:g} фактических часов"
                ),
            })
        if status in WORKING_STATUSES and planned > 0 and actual == 0:
            result.append({
                "type": "zero_hours_work_status",
                "severity": "warning",
                "date": item["work_date"],
                "entry_id": item["id"],
                "message": "Рабочий статус указан без фактических часов",
            })
        return result
