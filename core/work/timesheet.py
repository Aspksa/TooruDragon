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
        return self._decorate_entry(dict(rows[0]))

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
        return [self._decorate_entry(dict(item)) for item in rows]

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
