from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route
from core.work.documents import DOCUMENT_TYPES, DocumentIntelligenceService
from core.work.garage import GarageFuelService
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
    "document_intelligence",
    "document_passport",
    "document_dna",
    "document_versioning",
    "document_graph",
    "garage",
    "fuel_cards",
    "waybills",
    "fuel_statements",
    "fuel_reconciliation",
]

runtime = CoreRuntime(
    "work",
    "Рабочее ядро: проекты, документы, задачи, табель и рабочие интеграции",
    capabilities=CAPABILITIES,
)
timesheet = TimesheetService(runtime.db)
documents = DocumentIntelligenceService(runtime.db)
garage = GarageFuelService(runtime.db)


def capabilities(_request):
    return 200, {
        "service": "work",
        "capabilities": CAPABILITIES,
    }


def documents_status(_request):
    return 200, {
        "service": "work",
        "documents": {
            "enabled": True,
            "types": DOCUMENT_TYPES,
            "features": [
                "automatic_classification",
                "passport",
                "dna",
                "fact_provenance",
                "versioning",
                "deduplication",
                "logical_year_archive",
                "relations",
                "contradiction_checks",
                "rag_indexing",
                "safe_archive",
                "legacy_rag_migration",
            ],
        },
    }


def documents_list(request):
    document_type = str(request.query.get("type", [""])[0]).strip() or None
    status = str(request.query.get("status", [""])[0]).strip() or None
    year_raw = str(request.query.get("year", [""])[0]).strip()
    include_archived = str(
        request.query.get("include_archived", [""])[0]
    ).lower() in {"1", "true", "yes"}
    try:
        year = int(year_raw) if year_raw else None
        limit = int(request.query.get("limit", ["100"])[0])
        items = documents.documents(
            limit=limit,
            document_type=document_type,
            status=status,
            year=year,
            include_archived=include_archived,
        )
    except ValueError as exc:
        return 400, {"error": "invalid_document_filter", "message": str(exc)}
    return 200, {"service": "work", "documents": items}


def document_get(request):
    document_id = str(request.query.get("id", [""])[0]).strip()
    if not document_id:
        return 400, {"error": "document_id_required"}
    try:
        item = documents.document(document_id)
    except KeyError:
        return 404, {"error": "document_not_found"}
    return 200, {"service": "work", "document": item}


def document_search(request):
    query = str(request.query.get("q", [""])[0]).strip()
    if not query:
        return 200, {"service": "work", "documents": []}
    try:
        limit = int(request.query.get("limit", ["50"])[0])
    except ValueError:
        return 400, {"error": "invalid_limit"}
    return 200, {
        "service": "work",
        "documents": documents.search(query, limit=limit),
    }


def document_graph(_request):
    return 200, {
        "service": "work",
        "graph": documents.graph(),
    }


def document_stats(_request):
    return 200, {
        "service": "work",
        "stats": documents.stats(),
    }


def document_ingest_history(request):
    try:
        limit = int(request.query.get("limit", ["100"])[0])
    except ValueError:
        return 400, {"error": "invalid_limit"}
    return 200, {
        "service": "work",
        "history": documents.ingest_history(limit=limit),
    }


def document_file_ingest(request):
    payload = request.json if isinstance(request.json, dict) else {}
    filename = str(payload.get("filename") or "")
    source = str(payload.get("source") or "web_file")
    try:
        item = documents.ingest_file(payload)
    except ValueError as exc:
        documents.record_ingest_event(
            filename=filename,
            source=source,
            status="failed",
            error_type=type(exc).__name__,
            message=str(exc),
        )
        return 400, {
            "error": "document_file_ingest_failed",
            "message": str(exc),
            "filename": filename,
        }

    documents.record_ingest_event(
        filename=filename,
        source=source,
        status="duplicate" if item.get("duplicate") else "studied",
        document_id=item["id"],
    )
    fuel_import = None
    if item["document_type"] == "fuel_statement" and not item.get("duplicate"):
        try:
            fuel_import = {
                "ok": True,
                "statement": garage.import_fuel_statement(
                    document_id=item["id"],
                    original_name=filename,
                    content_base64=str(payload.get("content_base64") or ""),
                ),
            }
        except ValueError as exc:
            item = documents.record_issue(
                item["id"],
                "fuel_statement_import_failed",
                "error",
                "Выписка ГСМ сохранена, но операции не удалось импортировать в гараж.",
                {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            )
            fuel_import = {
                "ok": False,
                "message": str(exc),
            }

    runtime.events.publish(
        "work.document.file_ingested",
        "work",
        {
            "document_id": item["id"],
            "document_type": item["document_type"],
            "original_name": item["original_name"],
            "version": item["version"],
            "duplicate": bool(item.get("duplicate")),
            "issue_count": len(item.get("issues", [])),
            "fuel_import_ok": (
                fuel_import.get("ok")
                if isinstance(fuel_import, dict)
                else None
            ),
        },
    )
    return 200, {
        "service": "work",
        "document": item,
        "fuel_import": fuel_import,
    }


def document_ingest(request):
    payload = request.json if isinstance(request.json, dict) else {}
    title = str(payload.get("title") or "Вставленный текст")
    source = str(payload.get("source") or "web_text")
    try:
        item = documents.ingest(payload)
    except ValueError as exc:
        documents.record_ingest_event(
            filename=title,
            source=source,
            status="failed",
            error_type=type(exc).__name__,
            message=str(exc),
        )
        return 400, {"error": "invalid_document", "message": str(exc)}

    documents.record_ingest_event(
        filename=title,
        source=source,
        status="duplicate" if item.get("duplicate") else "studied",
        document_id=item["id"],
    )
    runtime.events.publish(
        "work.document.ingested",
        "work",
        {
            "document_id": item["id"],
            "document_type": item["document_type"],
            "version": item["version"],
            "duplicate": bool(item.get("duplicate")),
            "issue_count": len(item.get("issues", [])),
        },
    )
    return 200, {"service": "work", "document": item}


def document_migrate_legacy_rag(_request):
    result = documents.migrate_legacy_rag()
    runtime.events.publish(
        "work.document.legacy_rag_migrated",
        "work",
        {
            "requested": result["requested"],
            "migrated": result["migrated"],
            "duplicates": result["duplicates"],
            "failed": result["failed"],
        },
    )
    return 200, {"service": "work", "migration": result}


def document_reanalyze(request):
    payload = request.json if isinstance(request.json, dict) else {}
    document_id = str(payload.get("document_id", "")).strip()
    if not document_id:
        return 400, {"error": "document_id_required"}
    try:
        item = documents.reanalyze(document_id)
    except KeyError:
        return 404, {"error": "document_not_found"}
    runtime.events.publish(
        "work.document.reanalyzed",
        "work",
        {"document_id": document_id, "issue_count": len(item.get("issues", []))},
    )
    return 200, {"service": "work", "document": item}


def document_archive(request):
    payload = request.json if isinstance(request.json, dict) else {}
    document_id = str(payload.get("document_id", "")).strip()
    if not document_id:
        return 400, {"error": "document_id_required"}
    try:
        item = documents.archive(document_id)
    except KeyError:
        return 404, {"error": "document_not_found"}
    runtime.events.publish(
        "work.document.archived",
        "work",
        {"document_id": document_id},
    )
    return 200, {"service": "work", "document": item}


def garage_status(_request):
    return 200, {
        "service": "work",
        "garage": {
            "enabled": True,
            "features": [
                "vehicles",
                "driver_vehicle_history",
                "fuel_cards",
                "waybills",
                "fuel_statement_import",
                "monthly_fuel_reconciliation",
            ],
        },
    }


def garage_stats(_request):
    return 200, {"service": "work", "stats": garage.stats()}


def garage_employees(_request):
    return 200, {
        "service": "work",
        "employees": garage.employee_directory(),
    }


def garage_vehicles(_request):
    return 200, {
        "service": "work",
        "vehicles": garage.vehicles(active_only=False),
    }


def garage_vehicle_save(request):
    payload = request.json if isinstance(request.json, dict) else {}
    try:
        item = garage.save_vehicle(payload)
    except ValueError as exc:
        return 400, {"error": "invalid_vehicle", "message": str(exc)}
    except Exception as exc:
        if exc.__class__.__name__ == "IntegrityError":
            return 409, {
                "error": "vehicle_conflict",
                "message": "Госномер или VIN уже используется",
            }
        raise
    runtime.events.publish(
        "work.garage.vehicle.saved",
        "work",
        {
            "vehicle_id": item["id"],
            "registration_number": item["registration_number"],
        },
    )
    return 200, {"service": "work", "vehicle": item}


def garage_fuel_card_assign(request):
    payload = request.json if isinstance(request.json, dict) else {}
    employee_id = str(payload.get("employee_id") or "").strip()
    if not employee_id:
        return 400, {"error": "employee_id_required"}
    try:
        item = garage.set_employee_fuel_card(
            employee_id,
            str(payload.get("card_number") or ""),
            valid_from=str(payload.get("valid_from") or "").strip() or None,
            source="garage",
        )
    except KeyError:
        return 404, {"error": "employee_not_found"}
    except ValueError as exc:
        return 409, {"error": "fuel_card_conflict", "message": str(exc)}
    runtime.events.publish(
        "work.garage.fuel_card.assigned",
        "work",
        {
            "employee_id": employee_id,
            "card_number": item["card_number"],
        },
    )
    return 200, {"service": "work", "fuel_card": item}


def garage_driver_vehicle_assign(request):
    payload = request.json if isinstance(request.json, dict) else {}
    employee_id = str(payload.get("employee_id") or "").strip()
    vehicle_id = str(payload.get("vehicle_id") or "").strip()
    if not employee_id or not vehicle_id:
        return 400, {"error": "employee_and_vehicle_required"}
    try:
        item = garage.assign_driver_vehicle(
            employee_id,
            vehicle_id,
            valid_from=str(payload.get("valid_from") or "").strip() or None,
            source="garage",
            note=str(payload.get("note") or ""),
        )
    except KeyError:
        return 404, {"error": "employee_or_vehicle_not_found"}
    except ValueError as exc:
        return 400, {"error": "invalid_assignment", "message": str(exc)}
    runtime.events.publish(
        "work.garage.driver_vehicle.assigned",
        "work",
        {
            "employee_id": employee_id,
            "vehicle_id": vehicle_id,
        },
    )
    return 200, {"service": "work", "assignment": item}


def garage_waybills(request):
    month = str(request.query.get("month", [""])[0]).strip()
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        items = garage.waybills(month)
    except ValueError as exc:
        return 400, {"error": "invalid_month", "message": str(exc)}
    return 200, {"service": "work", "month": month, "waybills": items}


def garage_waybill_save(request):
    payload = request.json if isinstance(request.json, dict) else {}
    try:
        item = garage.save_waybill(payload)
    except KeyError:
        return 404, {"error": "employee_or_vehicle_not_found"}
    except ValueError as exc:
        return 400, {"error": "invalid_waybill", "message": str(exc)}
    runtime.events.publish(
        "work.garage.waybill.saved",
        "work",
        {
            "waybill_id": item["id"],
            "trip_date": item["trip_date"],
            "employee_id": item["employee_id"],
            "vehicle_id": item["vehicle_id"],
            "consumption_l": item["actual_consumption_l"],
        },
    )
    return 200, {"service": "work", "waybill": item}


def garage_fuel_statements(_request):
    return 200, {
        "service": "work",
        "statements": garage.statements(),
    }


def garage_fuel_unresolved(request):
    month = str(request.query.get("month", [""])[0]).strip() or None
    try:
        items = garage.unresolved_cards(month)
    except ValueError as exc:
        return 400, {"error": "invalid_month", "message": str(exc)}
    return 200, {
        "service": "work",
        "month": month,
        "unresolved_cards": items,
    }


def garage_fuel_summary(request):
    month = str(request.query.get("month", [""])[0]).strip()
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        data = garage.monthly_summary(month)
    except ValueError as exc:
        return 400, {"error": "invalid_month", "message": str(exc)}
    return 200, {"service": "work", "summary": data}


def garage_fuel_reconcile(_request):
    result = garage.reconcile_transactions()
    runtime.events.publish(
        "work.garage.fuel.reconciled",
        "work",
        result,
    )
    return 200, {"service": "work", "result": result}


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

    fuel_card_number = str(payload.get("fuel_card_number") or "").strip()
    if fuel_card_number:
        try:
            garage.set_employee_fuel_card(
                item["id"],
                fuel_card_number,
                valid_from=str(payload.get("fuel_card_valid_from") or "").strip() or None,
                source="employee_directory",
            )
            item = timesheet.employee(item["id"])
        except ValueError as exc:
            return 409, {
                "error": "fuel_card_conflict",
                "message": str(exc),
                "employee": item,
            }

    runtime.events.publish(
        "work.timesheet.employee.saved",
        "work",
        {
            "employee_id": item["id"],
            "personnel_number": item["personnel_number"],
            "fuel_card_number": item.get("fuel_card_number"),
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
        "/documents/status": Route(documents_status, protected=False),
        "/documents": Route(documents_list, protected=True),
        "/documents/get": Route(document_get, protected=True),
        "/documents/search": Route(document_search, protected=True),
        "/documents/graph": Route(document_graph, protected=True),
        "/documents/stats": Route(document_stats, protected=True),
        "/documents/ingest-history": Route(
            document_ingest_history,
            protected=True,
        ),
        "/documents/ingest": Route(
            document_ingest,
            method="POST",
            protected=True,
        ),
        "/documents/file-ingest": Route(
            document_file_ingest,
            method="POST",
            protected=True,
        ),
        "/documents/migrate-legacy-rag": Route(
            document_migrate_legacy_rag,
            method="POST",
            protected=True,
        ),
        "/documents/reanalyze": Route(
            document_reanalyze,
            method="POST",
            protected=True,
        ),
        "/documents/archive": Route(
            document_archive,
            method="POST",
            protected=True,
        ),
        "/garage/status": Route(garage_status, protected=False),
        "/garage/stats": Route(garage_stats, protected=True),
        "/garage/employees": Route(garage_employees, protected=True),
        "/garage/vehicles": Route(garage_vehicles, protected=True),
        "/garage/vehicle/save": Route(
            garage_vehicle_save,
            method="POST",
            protected=True,
        ),
        "/garage/fuel-card/assign": Route(
            garage_fuel_card_assign,
            method="POST",
            protected=True,
        ),
        "/garage/driver-vehicle/assign": Route(
            garage_driver_vehicle_assign,
            method="POST",
            protected=True,
        ),
        "/garage/waybills": Route(garage_waybills, protected=True),
        "/garage/waybill/save": Route(
            garage_waybill_save,
            method="POST",
            protected=True,
        ),
        "/garage/fuel/statements": Route(
            garage_fuel_statements,
            protected=True,
        ),
        "/garage/fuel/unresolved": Route(
            garage_fuel_unresolved,
            protected=True,
        ),
        "/garage/fuel/summary": Route(
            garage_fuel_summary,
            protected=True,
        ),
        "/garage/fuel/reconcile": Route(
            garage_fuel_reconcile,
            method="POST",
            protected=True,
        ),
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
