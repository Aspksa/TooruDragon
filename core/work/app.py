from __future__ import annotations

import base64
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route
from core.work.documents import DOCUMENT_TYPES, DocumentIntelligenceService
from core.work.garage import GarageFuelService
from core.work.timesheet import STATUS_CODES, TimesheetService
from core.work.waybills import WaybillAutomationService, WaybillBatchWorker

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
    "waybill_batch_processing",
    "waybill_ocr",
    "waybill_review",
    "waybill_overtime_candidates",
]

runtime = CoreRuntime(
    "work",
    "Рабочее ядро: проекты, документы, задачи, табель и рабочие интеграции",
    capabilities=CAPABILITIES,
)
timesheet = TimesheetService(runtime.db)
documents = DocumentIntelligenceService(runtime.db)
garage = GarageFuelService(runtime.db)
waybills = WaybillAutomationService(
    runtime.db,
    documents=documents,
    garage=garage,
    timesheet=timesheet,
)
waybill_worker = WaybillBatchWorker(waybills)


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
    if item["document_type"] == "fuel_statement":
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


def waybill_status(_request):
    return 200, {
        "service": "work",
        "waybills": {
            "enabled": True,
            "canonical_entity": "garage_waybills",
            "ocr_once": True,
            "ollama_used": False,
            "stages": [
                "uploaded",
                "splitting",
                "ocr",
                "extracting",
                "linking",
                "calculating",
                "validating",
                "completed",
            ],
            "priority": "P2",
            "worker": {
                "running": bool(
                    waybill_worker._thread
                    and waybill_worker._thread.is_alive()
                ),
                "last_error": waybill_worker.last_error,
            },
        },
    }


def waybill_batches(request):
    try:
        limit = int(request.query.get("limit", ["50"])[0])
    except ValueError:
        return 400, {"error": "invalid_limit"}
    return 200, {
        "service": "work",
        "batches": waybills.batches(limit=limit),
    }


def waybill_batch_get(request):
    batch_id = str(request.query.get("id", [""])[0]).strip()
    if not batch_id:
        return 400, {"error": "batch_id_required"}
    try:
        item = waybills.batch(batch_id)
        item["summary"] = waybills.batch_summary(batch_id)
    except KeyError:
        return 404, {"error": "batch_not_found"}
    return 200, {"service": "work", "batch": item}


def waybill_batch_pages(request):
    batch_id = str(request.query.get("id", [""])[0]).strip()
    if not batch_id:
        return 400, {"error": "batch_id_required"}
    try:
        waybills.batch(batch_id)
    except KeyError:
        return 404, {"error": "batch_not_found"}
    return 200, {
        "service": "work",
        "batch_id": batch_id,
        "pages": waybills.batch_pages(batch_id),
    }


def waybill_batch_upload_chunk(request):
    payload = request.json if isinstance(request.json, dict) else {}
    try:
        item = waybills.upload_chunk(payload)
    except (ValueError, OSError) as exc:
        return 400, {
            "error": "waybill_batch_upload_failed",
            "message": str(exc),
        }
    if item.get("complete"):
        runtime.events.publish(
            "work.waybill.batch.uploaded",
            "work",
            {
                "batch_id": item["id"],
                "sha256": item["sha256"],
                "duplicate": bool(item.get("duplicate")),
            },
        )
    return 200, {"service": "work", "upload": item}


def waybill_batch_upload(request):
    payload = request.json if isinstance(request.json, dict) else {}
    filename = str(payload.get("filename") or "").strip()
    encoded = str(payload.get("content_base64") or "").strip()
    if not filename or not encoded:
        return 400, {"error": "filename_and_content_required"}
    try:
        raw = base64.b64decode(encoded, validate=True)
        item = waybills.upload_bytes(
            filename=filename,
            raw=raw,
            uploaded_by=str(payload.get("uploaded_by") or "user"),
            source=str(payload.get("source") or "documents"),
        )
    except (ValueError, OSError) as exc:
        return 400, {
            "error": "waybill_batch_upload_failed",
            "message": str(exc),
        }
    runtime.events.publish(
        "work.waybill.batch.uploaded",
        "work",
        {
            "batch_id": item["id"],
            "sha256": item["sha256"],
            "duplicate": bool(item.get("duplicate")),
        },
    )
    return 200, {"service": "work", "batch": item}


def waybill_batch_reprocess(request):
    payload = request.json if isinstance(request.json, dict) else {}
    batch_id = str(payload.get("batch_id") or "").strip()
    if not batch_id:
        return 400, {"error": "batch_id_required"}
    try:
        batch = waybills.batch(batch_id)
    except KeyError:
        return 404, {"error": "batch_not_found"}
    task = waybills.workflow.create_task(
        kind="waybill.batch.process",
        payload={"batch_id": batch_id},
        priority=20,
        max_attempts=3,
        idempotency_key=f"waybill-batch-reprocess:{batch_id}:{batch['updated_at']}",
        required_capability="waybill_processing",
    )
    return 202, {"service": "work", "task": task}


def waybill_list(request):
    month = str(request.query.get("month", [""])[0]).strip() or None
    batch_id = str(request.query.get("batch_id", [""])[0]).strip() or None
    review_raw = str(request.query.get("needs_review", [""])[0]).strip().lower()
    review = None
    if review_raw in {"1", "true", "yes"}:
        review = True
    elif review_raw in {"0", "false", "no"}:
        review = False
    try:
        items = waybills.waybills(
            month=month,
            batch_id=batch_id,
            needs_review=review,
        )
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_waybill_filter", "message": str(exc)}
    return 200, {"service": "work", "waybills": items}


def waybill_get(request):
    waybill_id = str(request.query.get("id", [""])[0]).strip()
    if not waybill_id:
        return 400, {"error": "waybill_id_required"}
    try:
        item = waybills.waybill(waybill_id)
    except KeyError:
        return 404, {"error": "waybill_not_found"}
    return 200, {"service": "work", "waybill": item}


def waybill_field_correct(request):
    payload = request.json if isinstance(request.json, dict) else {}
    waybill_id = str(payload.get("waybill_id") or "").strip()
    field_key = str(payload.get("field_key") or "").strip()
    if not waybill_id or not field_key:
        return 400, {"error": "waybill_and_field_required"}
    try:
        item = waybills.correct_field(
            waybill_id,
            field_key=field_key,
            corrected_value=str(payload.get("value") or ""),
            actor=str(payload.get("actor") or "user"),
            reason=str(payload.get("reason") or ""),
        )
    except KeyError:
        return 404, {"error": "waybill_or_field_not_found"}
    except ValueError as exc:
        return 400, {"error": "invalid_waybill_correction", "message": str(exc)}
    return 200, {"service": "work", "waybill": item}


def waybill_confirm(request):
    payload = request.json if isinstance(request.json, dict) else {}
    waybill_id = str(payload.get("waybill_id") or "").strip()
    if not waybill_id:
        return 400, {"error": "waybill_id_required"}
    try:
        item = waybills.confirm_waybill(
            waybill_id,
            actor=str(payload.get("actor") or "user"),
            comment=str(payload.get("comment") or ""),
        )
    except KeyError:
        return 404, {"error": "waybill_not_found"}
    except ValueError as exc:
        return 409, {
            "error": "waybill_confirmation_blocked",
            "message": str(exc),
        }
    return 200, {"service": "work", "waybill": item}


def employee_schedules(request):
    employee_id = str(
        request.query.get("employee_id", [""])[0]
    ).strip() or None
    return 200, {
        "service": "work",
        "schedules": waybills.schedules(employee_id),
    }


def employee_schedule_save(request):
    payload = request.json if isinstance(request.json, dict) else {}
    try:
        item = waybills.save_schedule(payload)
    except KeyError:
        return 404, {"error": "employee_not_found"}
    except ValueError as exc:
        return 400, {"error": "invalid_schedule", "message": str(exc)}
    return 200, {"service": "work", "schedule": item}


def waybill_overtime_candidates(request):
    month = str(request.query.get("month", [""])[0]).strip() or None
    status = str(request.query.get("status", [""])[0]).strip() or None
    try:
        items = waybills.overtime_candidates(month=month, status=status)
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_overtime_filter", "message": str(exc)}
    return 200, {"service": "work", "candidates": items}


def waybill_monthly_mileage(request):
    month = str(request.query.get("month", [""])[0]).strip()
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        data = waybills.monthly_mileage_summary(month)
    except ValueError as exc:
        return 400, {"error": "invalid_month", "message": str(exc)}
    return 200, {"service": "work", "summary": data}


def waybill_overtime_summary(request):
    month = str(request.query.get("month", [""])[0]).strip()
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        data = waybills.overtime_month_summary(month)
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_month", "message": str(exc)}
    return 200, {"service": "work", "summary": data}


def waybill_overtime_review(request):
    payload = request.json if isinstance(request.json, dict) else {}
    candidate_id = str(payload.get("candidate_id") or "").strip()
    if not candidate_id:
        return 400, {"error": "candidate_id_required"}
    corrected = payload.get("corrected_total_minutes")
    try:
        item = waybills.review_overtime(
            candidate_id,
            action=str(payload.get("action") or ""),
            actor=str(payload.get("actor") or "user"),
            corrected_total_minutes=(
                int(corrected)
                if corrected not in {None, ""}
                else None
            ),
            comment=str(payload.get("comment") or ""),
        )
    except KeyError:
        return 404, {"error": "candidate_not_found"}
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_overtime_review", "message": str(exc)}
    runtime.events.publish(
        "work.waybill.overtime.reviewed",
        "work",
        {
            "candidate_id": item["id"],
            "waybill_id": item["waybill_id"],
            "status": item["status"],
        },
    )
    return 200, {"service": "work", "candidate": item}


def waybill_audit(request):
    entity_type = str(
        request.query.get("entity_type", [""])[0]
    ).strip() or None
    entity_id = str(
        request.query.get("entity_id", [""])[0]
    ).strip() or None
    return 200, {
        "service": "work",
        "audit": waybills.audit(
            entity_type=entity_type,
            entity_id=entity_id,
        ),
    }


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

    schedule_start = str(payload.get("workday_start") or "").strip()
    schedule_end = str(payload.get("workday_end") or "").strip()
    if schedule_start or schedule_end:
        if not schedule_start or not schedule_end:
            return 400, {
                "error": "invalid_schedule",
                "message": "Нужно указать и начало, и конец рабочего дня",
            }
        try:
            waybills.save_schedule({
                "employee_id": item["id"],
                "start_time": schedule_start,
                "end_time": schedule_end,
                "weekdays": payload.get("workdays", [0, 1, 2, 3, 4]),
                "source": "employee_directory",
                "actor": str(payload.get("actor") or "user"),
            })
        except ValueError as exc:
            return 400, {"error": "invalid_schedule", "message": str(exc)}

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
    runtime.db.initialize(runtime.version)
    waybill_worker.start()
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
        "/waybills/status": Route(waybill_status, protected=False),
        "/waybills/batches": Route(waybill_batches, protected=True),
        "/waybills/batch": Route(waybill_batch_get, protected=True),
        "/waybills/batch/pages": Route(waybill_batch_pages, protected=True),
        "/waybills": Route(waybill_list, protected=True),
        "/waybills/get": Route(waybill_get, protected=True),
        "/waybills/monthly-mileage": Route(
            waybill_monthly_mileage,
            protected=True,
        ),
        "/waybills/overtime": Route(
            waybill_overtime_candidates,
            protected=True,
        ),
        "/waybills/overtime/summary": Route(
            waybill_overtime_summary,
            protected=True,
        ),
        "/waybills/audit": Route(waybill_audit, protected=True),
        "/waybills/batch/upload-chunk": Route(
            waybill_batch_upload_chunk,
            method="POST",
            protected=True,
        ),
        "/waybills/batch/upload": Route(
            waybill_batch_upload,
            method="POST",
            protected=True,
        ),
        "/waybills/batch/reprocess": Route(
            waybill_batch_reprocess,
            method="POST",
            protected=True,
        ),
        "/waybills/field/correct": Route(
            waybill_field_correct,
            method="POST",
            protected=True,
        ),
        "/waybills/confirm": Route(
            waybill_confirm,
            method="POST",
            protected=True,
        ),
        "/waybills/overtime/review": Route(
            waybill_overtime_review,
            method="POST",
            protected=True,
        ),
        "/timesheet/schedules": Route(
            employee_schedules,
            protected=True,
        ),
        "/timesheet/schedule/save": Route(
            employee_schedule_save,
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
