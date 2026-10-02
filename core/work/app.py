from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route
from core.work.timesheet import STATUS_CODES, TimesheetService

CAPABILITIES = [
    "projects",
    "documents",
    "tasks",
    "work_integrations",
    "timesheet",
    "timesheet_analytics",
    "timesheet_custom_fields",
    "timesheet_overtime_analytics",
]

runtime = CoreRuntime(
    "work",
    "Рабочее ядро: проекты, документы, задачи, табель и рабочие интеграции",
    capabilities=CAPABILITIES,
)
timesheet = TimesheetService(runtime.db)


def capabilities(_request):
    return 200, {
        "service": "work",
        "capabilities": CAPABILITIES,
    }


def timesheet_status(_request):
    return 200, {
        "service": "work",
        "timesheet": {
            "enabled": True,
            "status_codes": STATUS_CODES,
            "features": [
                "employees",
                "month_calendar",
                "planned_actual_hours",
                "overtime",
                "night_hours",
                "anomaly_detection",
                "monthly_summary",
                "custom_fields",
                "overtime_analytics",
            ],
        },
    }


def employees(request):
    active = str(request.query.get("active", [""])[0]).lower()
    return 200, {
        "service": "work",
        "employees": timesheet.employees(
            active_only=active in {"1", "true", "yes"}
        ),
    }


def employee_save(request):
    payload = request.json if isinstance(request.json, dict) else {}
    try:
        item = timesheet.save_employee(payload)
    except ValueError as exc:
        return 400, {"error": "invalid_employee", "message": str(exc)}
    except Exception as exc:
        if exc.__class__.__name__ == "IntegrityError":
            return 409, {
                "error": "employee_conflict",
                "message": "Табельный номер уже используется",
            }
        raise

    runtime.events.publish(
        "work.timesheet.employee.saved",
        "work",
        {
            "employee_id": item["id"],
            "personnel_number": item["personnel_number"],
        },
    )
    return 200, {"service": "work", "employee": item}


def custom_columns(_request):
    return 200, {
        "service": "work",
        "columns": timesheet.custom_columns(active_only=False),
    }


def custom_column_save(request):
    payload = request.json if isinstance(request.json, dict) else {}
    try:
        item = timesheet.save_custom_column(payload)
    except ValueError as exc:
        return 400, {"error": "invalid_custom_column", "message": str(exc)}
    except Exception as exc:
        if exc.__class__.__name__ == "IntegrityError":
            return 409, {
                "error": "custom_column_conflict",
                "message": "Ключ пользовательского поля уже используется",
            }
        raise

    runtime.events.publish(
        "work.timesheet.custom_column.saved",
        "work",
        {
            "column_id": item["id"],
            "key": item["key"],
            "label": item["label"],
            "value_type": item["value_type"],
        },
    )
    return 200, {"service": "work", "column": item}


def entries(request):
    month = str(request.query.get("month", [""])[0]).strip()
    employee_id = str(
        request.query.get("employee_id", [""])[0]
    ).strip() or None
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        items = timesheet.entries(month, employee_id=employee_id)
    except ValueError as exc:
        return 400, {"error": "invalid_month", "message": str(exc)}
    return 200, {
        "service": "work",
        "month": month,
        "entries": items,
    }


def entry_save(request):
    payload = request.json if isinstance(request.json, dict) else {}
    try:
        item = timesheet.save_entry(payload)
    except KeyError:
        return 404, {"error": "employee_not_found"}
    except ValueError as exc:
        return 400, {"error": "invalid_timesheet_entry", "message": str(exc)}

    runtime.events.publish(
        "work.timesheet.entry.saved",
        "work",
        {
            "entry_id": item["id"],
            "employee_id": item["employee_id"],
            "work_date": item["work_date"],
            "status": item["status"],
            "actual_hours": item["actual_hours"],
            "overtime_hours": item["overtime_hours"],
        },
    )
    return 200, {"service": "work", "entry": item}


def month_calendar(request):
    month = str(request.query.get("month", [""])[0]).strip()
    employee_id = str(
        request.query.get("employee_id", [""])[0]
    ).strip() or None
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        data = timesheet.calendar(month, employee_id=employee_id)
    except KeyError:
        return 404, {"error": "employee_not_found"}
    except ValueError as exc:
        return 400, {"error": "invalid_month", "message": str(exc)}
    return 200, {"service": "work", "calendar": data}


def month_summary(request):
    month = str(request.query.get("month", [""])[0]).strip()
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        data = timesheet.summary(month)
    except ValueError as exc:
        return 400, {"error": "invalid_month", "message": str(exc)}
    return 200, {"service": "work", "summary": data}


def overtime_report(request):
    month = str(request.query.get("month", [""])[0]).strip()
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        data = timesheet.overtime_report(month)
    except ValueError as exc:
        return 400, {"error": "invalid_month", "message": str(exc)}
    return 200, {"service": "work", "overtime": data}


def month_anomalies(request):
    month = str(request.query.get("month", [""])[0]).strip()
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        data = timesheet.anomalies(month)
    except ValueError as exc:
        return 400, {"error": "invalid_month", "message": str(exc)}
    return 200, {
        "service": "work",
        "month": month,
        "anomalies": data,
    }


if __name__ == "__main__":
    runtime.run({
        "/capabilities": Route(capabilities, protected=False),
        "/timesheet/status": Route(timesheet_status, protected=False),
        "/timesheet/employees": Route(employees, protected=True),
        "/timesheet/custom-columns": Route(custom_columns, protected=True),
        "/timesheet/custom-column/save": Route(
            custom_column_save,
            method="POST",
            protected=True,
        ),
        "/timesheet/employee/save": Route(
            employee_save,
            method="POST",
            protected=True,
        ),
        "/timesheet/entries": Route(entries, protected=True),
        "/timesheet/entry/save": Route(
            entry_save,
            method="POST",
            protected=True,
        ),
        "/timesheet/calendar": Route(month_calendar, protected=True),
        "/timesheet/summary": Route(month_summary, protected=True),
        "/timesheet/overtime": Route(overtime_report, protected=True),
        "/timesheet/anomalies": Route(month_anomalies, protected=True),
    })
