from __future__ import annotations

import base64
import calendar
import hashlib
import io
import json
import re
import shutil
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from core.system.ai_memory import AIMemoryStore
from core.system.database import Database
from core.system.workflow import WorkflowEngine
from core.work.documents import DocumentIntelligenceService
from core.work.garage import GarageFuelService
from core.work.timesheet import TimesheetService
from core.work.waybill_extract import (
    extract_group_fields,
    looks_like_waybill_batch,
    normalize_name,
    normalize_plate,
    split_waybill_pages,
)
from core.work.waybill_ocr import OCRPage, OCRService, OCRUnavailableError


BATCH_STAGES = (
    "uploaded",
    "splitting",
    "ocr",
    "extracting",
    "linking",
    "calculating",
    "validating",
    "completed",
)
CRITICAL_FIELDS = {
    "trip_date",
    "vehicle_plate",
    "driver_name",
    "odometer_start",
    "odometer_end",
    "fuel_open_l",
    "fuel_close_l",
}
FIELD_THRESHOLD = 0.78
LINK_THRESHOLD = 0.90
MONTHS_RU = {
    1: "01 Январь",
    2: "02 Февраль",
    3: "03 Март",
    4: "04 Апрель",
    5: "05 Май",
    6: "06 Июнь",
    7: "07 Июль",
    8: "08 Август",
    9: "09 Сентябрь",
    10: "10 Октябрь",
    11: "11 Ноябрь",
    12: "12 Декабрь",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(value: str, fallback: str = "Не определено") -> str:
    cleaned = re.sub(
        r"[^A-Za-zА-Яа-яЁё0-9._()\- ]+",
        "_",
        str(value or ""),
    ).strip(" .")
    return cleaned or fallback


def _initials(name: str) -> str:
    parts = [
        part for part in re.split(r"\s+", str(name or "").strip())
        if part
    ]
    if not parts:
        return "Не определён"
    surname = parts[0]
    rest = "".join(f"{part[0].upper()}." for part in parts[1:3] if part)
    return f"{surname} {rest}".strip()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _minutes_hhmm(minutes: int) -> str:
    sign = "-" if minutes < 0 else ""
    minutes = abs(int(minutes))
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def _parse_clock(value: str | None) -> tuple[int, int] | None:
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", raw):
        return None
    hour, minute = map(int, raw.split(":"))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


class WaybillAutomationService:
    def __init__(
        self,
        database: Database,
        *,
        documents: DocumentIntelligenceService | None = None,
        garage: GarageFuelService | None = None,
        timesheet: TimesheetService | None = None,
        workflow: WorkflowEngine | None = None,
        memory: AIMemoryStore | None = None,
        ocr: OCRService | None = None,
    ):
        self.db = database
        self.documents = documents or DocumentIntelligenceService(database)
        self.garage = garage or GarageFuelService(database)
        self.timesheet = timesheet or TimesheetService(database)
        self.workflow = workflow or WorkflowEngine(database)
        self.memory = memory or AIMemoryStore(database)
        self.ocr = ocr or OCRService()

    # ------------------------------------------------------------------ upload

    @property
    def data_root(self) -> Path:
        return self.db.path.parent

    @property
    def upload_root(self) -> Path:
        return self.data_root / "uploads" / "waybill_batches"

    def upload_chunk(self, payload: dict) -> dict:
        upload_id = str(payload.get("upload_id") or "").strip() or str(uuid4())
        filename = str(payload.get("filename") or "").strip()
        if not filename:
            raise ValueError("filename is required")
        try:
            index = int(payload.get("chunk_index"))
            total = int(payload.get("total_chunks"))
        except (TypeError, ValueError) as exc:
            raise ValueError("chunk_index and total_chunks are required") from exc
        if index < 0 or total <= 0 or index >= total:
            raise ValueError("invalid chunk coordinates")

        encoded = str(payload.get("content_base64") or "")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError("invalid base64 chunk") from exc
        if len(raw) > 6_000_000:
            raise ValueError("upload chunk is larger than 6 MB")

        root = self.upload_root / _safe(upload_id, upload_id)
        root.mkdir(parents=True, exist_ok=True)
        meta_path = root / "upload.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta["filename"] != filename or int(meta["total_chunks"]) != total:
                raise ValueError("upload_id metadata conflict")
        else:
            meta = {
                "upload_id": upload_id,
                "filename": filename,
                "total_chunks": total,
                "uploaded_by": str(payload.get("uploaded_by") or "user"),
                "source": str(payload.get("source") or "documents"),
            }
            meta_path.write_text(_json(meta), encoding="utf-8")

        part = root / f"{index:06d}.part"
        if not part.exists():
            temporary = part.with_suffix(".tmp")
            temporary.write_bytes(raw)
            temporary.replace(part)

        received = len(list(root.glob("*.part")))
        if received < total:
            return {
                "upload_id": upload_id,
                "received_chunks": received,
                "total_chunks": total,
                "complete": False,
            }

        assembled = root / "assembled.bin"
        digest = hashlib.sha256()
        size = 0
        with assembled.open("wb") as output:
            for chunk_index in range(total):
                path = root / f"{chunk_index:06d}.part"
                if not path.exists():
                    raise ValueError(f"missing upload chunk {chunk_index}")
                data = path.read_bytes()
                output.write(data)
                digest.update(data)
                size += len(data)

        result = self._register_batch_file(
            filename=filename,
            assembled_path=assembled,
            sha256=digest.hexdigest(),
            size_bytes=size,
            uploaded_by=meta["uploaded_by"],
            source=meta["source"],
        )
        result["upload_id"] = upload_id
        result["received_chunks"] = total
        result["total_chunks"] = total
        result["complete"] = True
        return result

    def upload_bytes(
        self,
        *,
        filename: str,
        raw: bytes,
        uploaded_by: str = "user",
        source: str = "documents",
    ) -> dict:
        if not filename:
            raise ValueError("filename is required")
        if not raw:
            raise ValueError("file is empty")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
            raise ValueError("waybill batch supports PDF/JPG/PNG/TIFF")
        digest = hashlib.sha256(raw).hexdigest()
        self.upload_root.mkdir(parents=True, exist_ok=True)
        temp = self.upload_root / f"{uuid4()}.upload"
        temp.write_bytes(raw)
        try:
            return self._register_batch_file(
                filename=filename,
                assembled_path=temp,
                sha256=digest,
                size_bytes=len(raw),
                uploaded_by=uploaded_by,
                source=source,
            )
        finally:
            temp.unlink(missing_ok=True)

    def _register_batch_file(
        self,
        *,
        filename: str,
        assembled_path: Path,
        sha256: str,
        size_bytes: int,
        uploaded_by: str,
        source: str,
    ) -> dict:
        duplicate = self.db.query(
            """
            SELECT id
            FROM work_waybill_batches
            WHERE sha256=?
            LIMIT 1
            """,
            (sha256,),
        )
        if duplicate:
            item = self.batch(duplicate[0]["id"])
            item["duplicate"] = True
            return item

        batch_id = str(uuid4())
        safe_name = _safe(Path(filename).name, "waybills.pdf")
        relative = (
            Path("documents")
            / "Путевые листы"
            / "Оригиналы"
            / batch_id
            / safe_name
        )
        target = self.data_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(str(target))
        temporary = target.with_suffix(target.suffix + ".tmp")
        shutil.copyfile(assembled_path, temporary)
        temporary.replace(target)

        document = self.documents.ingest({
            "_document_id": batch_id,
            "_archive_path": "Путевые листы/Оригиналы",
            "title": f"Пачка путевых листов · {Path(filename).stem}",
            "original_name": filename,
            "text": (
                "Пачка путевых листов\n"
                f"Исходный файл: {filename}\n"
                f"SHA-256: {sha256}\n"
                f"Размер: {size_bytes} байт\n"
                f"Источник: {source}\n"
                f"Загрузил: {uploaded_by}"
            ),
            "source": "waybill_batch",
            "source_path": relative.as_posix(),
            "document_type": "waybill_batch",
            "family_id": batch_id,
            "metadata": {
                "waybill_batch": {
                    "batch_id": batch_id,
                    "sha256": sha256,
                    "size_bytes": size_bytes,
                    "uploaded_by": uploaded_by,
                    "source": source,
                    "status": "uploaded",
                }
            },
        })

        now = _now()
        self.db.execute(
            """
            INSERT INTO work_waybill_batches(
                id, document_id, original_name, source_path, sha256,
                size_bytes, page_count, uploaded_by, source, status, stage,
                pages_processed, pages_ocr, waybills_detected,
                waybills_completed, errors_count, review_count,
                progress_json, error, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, 0, ?, ?, 'uploaded', 'uploaded',
                   0, 0, 0, 0, 0, 0, '{}', '', ?, ?)
            """,
            (
                batch_id,
                document["id"],
                filename,
                relative.as_posix(),
                sha256,
                int(size_bytes),
                uploaded_by,
                source,
                now,
                now,
            ),
        )
        task = self.workflow.create_task(
            kind="waybill.batch.process",
            payload={"batch_id": batch_id},
            priority=20,
            max_attempts=3,
            idempotency_key=f"waybill-batch:{sha256}",
            required_capability="waybill_processing",
        )
        self._set_batch(
            batch_id,
            progress={
                "task_id": task["id"],
                "priority": "P2",
                "message": "Пачка поставлена в очередь",
            },
        )
        self._audit(
            actor=uploaded_by,
            action="waybill_batch_uploaded",
            entity_type="waybill_batch",
            entity_id=batch_id,
            new_value=sha256,
            reason="user_upload",
            source=source,
            source_document_id=document["id"],
        )
        result = self.batch(batch_id)
        result["task"] = task
        result["duplicate"] = False
        return result

    # -------------------------------------------------------------- processing

    def process_batch(self, batch_id: str) -> dict:
        batch = self.batch(batch_id)
        if batch["status"] == "completed":
            return batch

        source_path = self.data_root / batch["source_path"]
        if not source_path.exists():
            raise FileNotFoundError(str(source_path))
        raw = source_path.read_bytes()

        try:
            self._set_batch(
                batch_id,
                status="processing",
                stage="splitting",
                error="",
                progress={"message": "Подготовка страниц и границ документов"},
            )
            self._set_batch(
                batch_id,
                stage="ocr",
                progress={"message": "Распознавание страниц"},
            )
            pages = self._cached_or_ocr_pages(batch_id, batch["original_name"], raw)
            self._set_batch(
                batch_id,
                page_count=len(pages),
                pages_ocr=len(pages),
                pages_processed=len(pages),
                progress={
                    "message": "Определение границ путевых листов",
                    "pages": len(pages),
                },
            )
            if not looks_like_waybill_batch(pages):
                raise ValueError(
                    "Документ не похож на пачку путевых листов: недостаточно "
                    "структурных признаков."
                )

            groups = split_waybill_pages(pages)
            self._set_batch(
                batch_id,
                waybills_detected=len(groups),
                stage="extracting",
                progress={
                    "message": "Извлечение карточек Waybill",
                    "groups": len(groups),
                },
            )

            waybill_ids = []
            review_count = 0
            errors = 0
            for index, group in enumerate(groups, start=1):
                try:
                    waybill = self._create_waybill(
                        batch=batch,
                        group=group,
                        sequence=index,
                        raw_batch=raw,
                    )
                    waybill_ids.append(waybill["id"])
                    if waybill["needs_review"]:
                        review_count += 1
                except Exception as exc:
                    errors += 1
                    self._record_batch_error(
                        batch_id,
                        f"Группа {index}: {type(exc).__name__}: {exc}",
                    )

                self._set_batch(
                    batch_id,
                    waybills_completed=len(waybill_ids),
                    errors_count=errors,
                    review_count=review_count,
                    stage="linking",
                    progress={
                        "message": "Привязка водителей и автомобилей",
                        "current": index,
                        "total": len(groups),
                    },
                )

            self._set_batch(
                batch_id,
                stage="calculating",
                progress={"message": "Расчёт пробега, ГСМ и переработки"},
            )
            for waybill_id in waybill_ids:
                self._recalculate_waybill(waybill_id)
                self._build_overtime_candidate(waybill_id)
                self._write_memory_and_graph(waybill_id)

            self._set_batch(
                batch_id,
                stage="validating",
                progress={"message": "Проверка последовательности и аномалий"},
            )
            self.validate_batch(batch_id)
            self._validate_fuel_transactions_for_batch(batch_id)

            summary = self.batch_summary(batch_id)
            status = "completed"
            self._set_batch(
                batch_id,
                status=status,
                stage="completed",
                errors_count=summary["errors"],
                review_count=summary["needs_review"],
                waybills_completed=summary["waybills"],
                progress={
                    "message": "Обработка завершена",
                    "summary": summary,
                },
            )
            self._audit(
                actor="system",
                action="waybill_batch_completed",
                entity_type="waybill_batch",
                entity_id=batch_id,
                new_value=_json(summary),
                reason="automation_completed",
                source="waybill_worker",
                source_document_id=batch["document_id"],
            )
            return self.batch(batch_id)
        except Exception as exc:
            self._set_batch(
                batch_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                errors_count=max(1, int(batch.get("errors_count") or 0) + 1),
                progress={"message": "Обработка остановлена", "error": str(exc)},
            )
            self.documents.record_issue(
                batch["document_id"],
                "waybill_batch_processing_failed",
                "error",
                "Пачку путевых листов не удалось обработать.",
                {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            )
            raise

    def _cached_or_ocr_pages(
        self,
        batch_id: str,
        filename: str,
        raw: bytes,
    ) -> list[OCRPage]:
        cached = self.db.query(
            """
            SELECT page_number, ocr_engine, ocr_text, ocr_blocks_json,
                   ocr_tables_json, confidence, image_path, status
            FROM work_waybill_batch_pages
            WHERE batch_id=? AND status='ocr_done'
            ORDER BY page_number
            """,
            (batch_id,),
        )
        batch = self.batch(batch_id)
        if cached and int(batch.get("page_count") or 0) == len(cached):
            return [
                OCRPage(
                    page_number=int(item["page_number"]),
                    text=item["ocr_text"],
                    confidence=float(item["confidence"]),
                    engine=item["ocr_engine"],
                    blocks=json.loads(item["ocr_blocks_json"] or "[]"),
                    tables=json.loads(item["ocr_tables_json"] or "[]"),
                    image_path=item["image_path"],
                )
                for item in cached
            ]

        pages = self.ocr.extract_pages(filename, raw)
        if not pages:
            raise OCRUnavailableError("OCR returned zero pages")
        now = _now()
        with self.db.connect() as db:
            for page in pages:
                db.execute(
                    """
                    INSERT INTO work_waybill_batch_pages(
                        id, batch_id, page_number, waybill_id, ocr_engine,
                        ocr_text, ocr_blocks_json, ocr_tables_json,
                        confidence, image_path, status, error,
                        created_at, updated_at
                    )
                    VALUES(?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, 'ocr_done', '', ?, ?)
                    ON CONFLICT(batch_id, page_number)
                    DO UPDATE SET
                        ocr_engine=excluded.ocr_engine,
                        ocr_text=excluded.ocr_text,
                        ocr_blocks_json=excluded.ocr_blocks_json,
                        ocr_tables_json=excluded.ocr_tables_json,
                        confidence=excluded.confidence,
                        image_path=excluded.image_path,
                        status='ocr_done',
                        error='',
                        updated_at=excluded.updated_at
                    """,
                    (
                        str(uuid4()),
                        batch_id,
                        page.page_number,
                        page.engine,
                        page.text,
                        _json(page.blocks),
                        _json(page.tables),
                        float(page.confidence),
                        page.image_path,
                        now,
                        now,
                    ),
                )
        self._set_batch(batch_id, page_count=len(pages), pages_ocr=len(pages))
        return pages

    # --------------------------------------------------------------- extraction

    def _create_waybill(
        self,
        *,
        batch: dict,
        group: dict,
        sequence: int,
        raw_batch: bytes,
    ) -> dict:
        pages: list[OCRPage] = group["pages"]
        page_numbers = list(group["page_numbers"])
        page_key = ",".join(str(value) for value in page_numbers)
        waybill_id = str(uuid5(UUID(batch["id"]), page_key))

        existing = self.db.query(
            "SELECT id FROM garage_waybills WHERE id=?",
            (waybill_id,),
        )
        if existing:
            recovered = self.waybill(waybill_id)
            recovered_fields = {
                item["field_key"]: {
                    "value": item["value"],
                    "confidence": item["confidence"],
                }
                for item in recovered.get("fields", [])
            }
            recovered_missing = [
                key
                for key in ("trip_date", "vehicle_plate", "driver_name")
                if not self._value(recovered_fields, key)
            ]
            recovered_low = [
                key
                for key, item in recovered_fields.items()
                if key in CRITICAL_FIELDS
                and float(item.get("confidence") or 0) < FIELD_THRESHOLD
            ]
            self._ensure_waybill_document(
                waybill_id=waybill_id,
                batch=batch,
                pages=pages,
                raw_batch=raw_batch,
                sequence=sequence,
            )
            self._seed_waybill_anomalies(
                waybill_id,
                fields=recovered_fields,
                missing_critical=recovered_missing,
                low_critical=recovered_low,
                vehicle_id=recovered.get("vehicle_id"),
                employee_id=recovered.get("employee_id"),
                split_needs_review=bool(group.get("needs_review")),
            )
            return self.waybill(waybill_id)

        fields = extract_group_fields(pages)

        trip_date = self._value(fields, "trip_date")
        waybill_number = self._value(fields, "waybill_number")
        plate = self._value(fields, "vehicle_plate")
        driver_name = self._value(fields, "driver_name")
        personnel_number = self._value(fields, "personnel_number")
        card_number = self._value(fields, "fuel_card_number")

        vehicle_id, vehicle_confidence = self._resolve_vehicle(
            plate=plate,
            vin=self._value(fields, "vehicle_vin"),
        )
        employee_id, employee_confidence = self._resolve_employee(
            driver_name=driver_name,
            personnel_number=personnel_number,
            fuel_card_number=card_number,
            vehicle_id=vehicle_id,
            trip_date=trip_date,
        )

        field_confidences = [
            float(item["confidence"])
            for key, item in fields.items()
            if key in CRITICAL_FIELDS
        ]
        ocr_confidence = (
            sum(page.confidence for page in pages) / len(pages)
            if pages
            else 0.0
        )
        extraction_confidence = (
            sum(field_confidences) / len(field_confidences)
            if field_confidences
            else 0.0
        )
        link_parts = [
            value for value in (vehicle_confidence, employee_confidence)
            if value > 0
        ]
        link_confidence = (
            sum(link_parts) / len(link_parts)
            if link_parts
            else 0.0
        )
        overall = round(
            ocr_confidence * 0.35
            + extraction_confidence * 0.4
            + link_confidence * 0.25,
            4,
        )

        missing_critical = [
            key
            for key in ("trip_date", "vehicle_plate", "driver_name")
            if not self._value(fields, key)
        ]
        low_critical = [
            key
            for key, item in fields.items()
            if key in CRITICAL_FIELDS
            and float(item["confidence"]) < FIELD_THRESHOLD
        ]
        needs_review = bool(
            group.get("needs_review")
            or missing_critical
            or low_critical
            or vehicle_id is None
            or employee_id is None
        )

        vehicle = self.garage.vehicle(vehicle_id) if vehicle_id else None
        employee = self._employee(employee_id) if employee_id else None
        folder = self._folder_path(
            trip_date=trip_date,
            plate=plate,
            vehicle=vehicle,
            driver_name=driver_name,
            employee=employee,
        )
        individual_path = self._export_waybill_pdf(
            batch=batch,
            raw_batch=raw_batch,
            page_numbers=page_numbers,
            folder_path=folder,
            trip_date=trip_date,
            waybill_number=waybill_number,
            sequence=sequence,
        )

        numeric = {
            key: self._number_value(fields, key)
            for key in (
                "odometer_start",
                "odometer_end",
                "fuel_open_l",
                "fuel_close_l",
                "fuel_issued_l",
                "refueled_l",
            )
        }
        distance = self._distance(
            numeric["odometer_start"],
            numeric["odometer_end"],
        )
        fuel_open = numeric["fuel_open_l"] or 0.0
        fuel_issued = numeric["fuel_issued_l"] or 0.0
        refueled = numeric["refueled_l"] or 0.0
        fuel_close = numeric["fuel_close_l"] or 0.0
        actual = round(fuel_open + fuel_issued + refueled - fuel_close, 4)

        norm = (
            float(vehicle["default_norm_l_per_100km"])
            if vehicle and vehicle.get("default_norm_l_per_100km") is not None
            else None
        )
        norm_consumption = (
            round(distance * norm / 100.0, 4)
            if distance is not None and norm is not None
            else None
        )
        deviation = (
            round(actual - norm_consumption, 4)
            if norm_consumption is not None
            else None
        )

        now = _now()
        with self.db.connect() as db:
            db.execute(
                """
                INSERT INTO garage_waybills(
                    id, waybill_number, trip_date, employee_id, vehicle_id,
                    odometer_start, odometer_end, distance_km,
                    fuel_open_l, fuel_issued_l, fuel_close_l,
                    norm_l_per_100km, actual_consumption_l,
                    norm_consumption_l, deviation_l, source_document_id,
                    batch_id, organization, department, vehicle_make,
                    vehicle_model, vehicle_vin, garage_number, driver_name,
                    personnel_number, departure_time, return_time,
                    refueled_l, fuel_name, route, assignment_text,
                    fuel_card_number, source_pages_json, confidence,
                    needs_review, processing_status, folder_path,
                    individual_pdf_path, note, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, 'extracted', ?, ?, ?, ?, ?)
                """,
                (
                    waybill_id,
                    waybill_number,
                    trip_date,
                    employee_id,
                    vehicle_id,
                    numeric["odometer_start"],
                    numeric["odometer_end"],
                    distance or 0.0,
                    fuel_open,
                    fuel_issued,
                    fuel_close,
                    norm,
                    actual,
                    norm_consumption,
                    deviation,
                    batch["id"],
                    self._value(fields, "organization"),
                    self._value(fields, "department"),
                    self._vehicle_make(fields, vehicle),
                    self._vehicle_model(fields, vehicle),
                    self._value(fields, "vehicle_vin"),
                    self._value(fields, "garage_number"),
                    driver_name,
                    personnel_number,
                    self._value(fields, "departure_time") or None,
                    self._value(fields, "return_time") or None,
                    refueled,
                    self._value(fields, "fuel_name"),
                    self._value(fields, "route"),
                    self._value(fields, "assignment_text"),
                    card_number,
                    _json(page_numbers),
                    overall,
                    1 if needs_review else 0,
                    folder,
                    individual_path,
                    self._value(fields, "note"),
                    now,
                    now,
                ),
            )
            for key, item in fields.items():
                db.execute(
                    """
                    INSERT INTO garage_waybill_fields(
                        waybill_id, field_key, original_value, corrected_value,
                        confidence, verified, provenance_json, corrected_at,
                        corrected_by, updated_at
                    )
                    VALUES(?, ?, ?, NULL, ?, 0, ?, NULL, NULL, ?)
                    """,
                    (
                        waybill_id,
                        key,
                        str(item.get("value") or ""),
                        float(item.get("confidence") or 0),
                        _json({
                            "batch_id": batch["id"],
                            "page_number": item.get("page_number"),
                            "excerpt": item.get("excerpt"),
                            "char_start": item.get("char_start"),
                            "char_end": item.get("char_end"),
                        }),
                        now,
                    ),
                )

        self._ensure_waybill_document(
            waybill_id=waybill_id,
            batch=batch,
            pages=pages,
            raw_batch=raw_batch,
            sequence=sequence,
        )

        self._seed_waybill_anomalies(
            waybill_id,
            fields=fields,
            missing_critical=missing_critical,
            low_critical=low_critical,
            vehicle_id=vehicle_id,
            employee_id=employee_id,
            split_needs_review=bool(group.get("needs_review")),
        )
        return self.waybill(waybill_id)

    def _ensure_waybill_document(
        self,
        *,
        waybill_id: str,
        batch: dict,
        pages: list[OCRPage],
        raw_batch: bytes,
        sequence: int,
    ) -> None:
        waybill = self.waybill(waybill_id)
        page_numbers = list(waybill.get("source_pages") or [])
        folder = waybill.get("folder_path") or "Путевые листы/Без сортировки"
        individual_path = waybill.get("individual_pdf_path") or ""
        if not individual_path:
            individual_path = self._export_waybill_pdf(
                batch=batch,
                raw_batch=raw_batch,
                page_numbers=page_numbers,
                folder_path=folder,
                trip_date=waybill.get("trip_date") or "",
                waybill_number=waybill.get("waybill_number") or "",
                sequence=sequence,
            )
            if individual_path:
                self.db.execute(
                    """
                    UPDATE garage_waybills
                    SET individual_pdf_path=?, updated_at=?
                    WHERE id=?
                    """,
                    (individual_path, _now(), waybill_id),
                )

        try:
            document = self.documents.document(
                waybill_id,
                include_text=False,
            )
        except KeyError:
            card_title = self._waybill_title(
                waybill.get("trip_date") or "",
                waybill.get("waybill_number") or "",
                waybill.get("registration_number") or "",
                waybill.get("full_name") or waybill.get("driver_name") or "",
                sequence,
            )
            ocr_text = "\n\n".join(
                f"[Страница {page.page_number}]\n{page.text}"
                for page in pages
            )
            document_text = (
                f"{ocr_text}\n\n"
                f"[Источник Waybill: {waybill_id}; batch={batch['id']}; "
                f"pages={','.join(map(str, page_numbers))}]"
            )
            document = self.documents.ingest({
                "_document_id": waybill_id,
                "_archive_path": folder,
                "title": card_title,
                "original_name": (
                    Path(individual_path).name
                    if individual_path
                    else batch["original_name"]
                ),
                "text": document_text,
                "source": "waybill_automation",
                "source_path": (
                    individual_path
                    or f"{batch['source_path']}#pages={','.join(map(str, page_numbers))}"
                ),
                "document_type": "waybill",
                "family_id": waybill_id,
                "metadata": {
                    "waybill": {
                        "waybill_id": waybill_id,
                        "batch_id": batch["id"],
                        "source_pages": page_numbers,
                        "confidence": waybill.get("confidence"),
                        "needs_review": bool(waybill.get("needs_review")),
                        "ocr_once": True,
                    }
                },
            })

        self.db.execute(
            """
            UPDATE garage_waybills
            SET source_document_id=?, processing_status=?, updated_at=?
            WHERE id=?
            """,
            (
                document["id"],
                "needs_review"
                if waybill.get("needs_review")
                else "studied",
                _now(),
                waybill_id,
            ),
        )
        with self.db.connect() as db:
            for page_number in page_numbers:
                db.execute(
                    """
                    UPDATE work_waybill_batch_pages
                    SET waybill_id=?, updated_at=?
                    WHERE batch_id=? AND page_number=?
                    """,
                    (waybill_id, _now(), batch["id"], page_number),
                )
        self._link_document_to_batch(waybill_id, batch["document_id"])

        if Path(batch["original_name"]).suffix.lower() == ".pdf" and not individual_path:
            self._anomaly(
                waybill_id,
                "individual_pdf_export_unavailable",
                "warning",
                "Отдельный PDF путевого листа не создан; сохранена связь со страницами исходного PDF.",
                {"source_pages": page_numbers},
            )

    def _export_waybill_pdf(
        self,
        *,
        batch: dict,
        raw_batch: bytes,
        page_numbers: list[int],
        folder_path: str,
        trip_date: str,
        waybill_number: str,
        sequence: int,
    ) -> str:
        suffix = Path(batch["original_name"]).suffix.lower()
        stem_date = trip_date or "Без_даты"
        number = _safe(waybill_number, str(sequence))
        filename = f"{stem_date}_ПЛ_{number}.pdf"
        relative = Path("documents") / Path(folder_path) / filename
        target = self.data_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return relative.as_posix()

        if suffix == ".pdf":
            try:
                from pypdf import PdfReader, PdfWriter
                reader = PdfReader(io.BytesIO(raw_batch))
                writer = PdfWriter()
                for page_number in page_numbers:
                    writer.add_page(reader.pages[page_number - 1])
                temporary = target.with_suffix(".pdf.tmp")
                with temporary.open("wb") as stream:
                    writer.write(stream)
                temporary.replace(target)
                return relative.as_posix()
            except Exception:
                return ""

        if suffix in {".jpg", ".jpeg", ".png", ".tif", ".tiff"} and page_numbers == [1]:
            # The source image remains immutable. A separate PDF derivative
            # requires a raster-to-PDF backend; keep the source page reference
            # if none is available.
            return ""
        return ""

    # -------------------------------------------------------------- resolution

    def _resolve_vehicle(
        self,
        *,
        plate: str,
        vin: str,
    ) -> tuple[str | None, float]:
        vehicles = self.garage.vehicles(active_only=False)
        normalized_plate = normalize_plate(plate)
        normalized_vin = re.sub(r"\s+", "", str(vin or "").upper())

        if normalized_vin:
            matches = [
                item for item in vehicles
                if re.sub(r"\s+", "", str(item.get("vin") or "").upper())
                == normalized_vin
            ]
            if len(matches) == 1:
                return matches[0]["id"], 1.0

        if normalized_plate:
            matches = [
                item for item in vehicles
                if normalize_plate(item.get("registration_number") or "")
                == normalized_plate
            ]
            if len(matches) == 1:
                return matches[0]["id"], 0.99
        return None, 0.0

    def _resolve_employee(
        self,
        *,
        driver_name: str,
        personnel_number: str,
        fuel_card_number: str,
        vehicle_id: str | None,
        trip_date: str,
    ) -> tuple[str | None, float]:
        employees = self.timesheet.employees(active_only=False)
        if personnel_number:
            exact = [
                item for item in employees
                if str(item.get("personnel_number") or "").strip().upper()
                == personnel_number.strip().upper()
            ]
            if len(exact) == 1:
                return exact[0]["id"], 1.0

        if fuel_card_number and trip_date:
            rows = self.db.query(
                """
                SELECT employee_id
                FROM work_employee_fuel_cards
                WHERE card_number=?
                  AND (valid_from IS NULL OR valid_from<=?)
                  AND (valid_to IS NULL OR valid_to>=?)
                ORDER BY active DESC, COALESCE(valid_from, '') DESC
                LIMIT 2
                """,
                (re.sub(r"\D+", "", fuel_card_number), trip_date, trip_date),
            )
            if len(rows) == 1:
                card_employee = rows[0]["employee_id"]
                if not driver_name:
                    return card_employee, 0.99
                expected = self._employee(card_employee)
                if self._name_match(driver_name, expected["full_name"]) >= 0.9:
                    return card_employee, 0.995

        if driver_name:
            scored = []
            for item in employees:
                score = self._name_match(driver_name, item["full_name"])
                if score <= 0:
                    continue
                if vehicle_id and trip_date:
                    assigned = self.db.query(
                        """
                        SELECT 1
                        FROM garage_driver_vehicle_assignments
                        WHERE employee_id=? AND vehicle_id=?
                          AND (valid_from IS NULL OR valid_from<=?)
                          AND (valid_to IS NULL OR valid_to>=?)
                        LIMIT 1
                        """,
                        (item["id"], vehicle_id, trip_date, trip_date),
                    )
                    if assigned:
                        score = min(1.0, score + 0.03)
                scored.append((score, item["id"]))
            scored.sort(reverse=True)
            if scored and scored[0][0] >= LINK_THRESHOLD:
                if len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.04:
                    return scored[0][1], round(scored[0][0], 4)
        return None, 0.0

    @staticmethod
    def _name_match(extracted: str, stored: str) -> float:
        left = normalize_name(extracted)
        right = normalize_name(stored)
        if not left or not right:
            return 0.0
        if left == right:
            return 0.99

        lparts = left.split()
        rparts = right.split()
        if not lparts or not rparts or lparts[0] != rparts[0]:
            return 0.0

        if len(lparts) == 1:
            return 0.88

        extracted_initials = [
            part[0] for part in lparts[1:] if part
        ]
        stored_initials = [
            part[0] for part in rparts[1:] if part
        ]
        if extracted_initials and stored_initials:
            count = min(len(extracted_initials), len(stored_initials))
            if extracted_initials[:count] == stored_initials[:count]:
                return 0.95 if count >= 2 else 0.92
        return 0.82

    # --------------------------------------------------------------- validation

    def _seed_waybill_anomalies(
        self,
        waybill_id: str,
        *,
        fields: dict,
        missing_critical: list[str],
        low_critical: list[str],
        vehicle_id: str | None,
        employee_id: str | None,
        split_needs_review: bool,
    ) -> None:
        if split_needs_review:
            self._anomaly(
                waybill_id,
                "split_low_confidence",
                "warning",
                "Границы путевого листа требуют проверки.",
                {},
            )
        for key in missing_critical:
            self._anomaly(
                waybill_id,
                f"missing_{key}",
                "warning",
                f"Не удалось распознать критическое поле: {key}.",
                {},
            )
        for key in low_critical:
            item = fields[key]
            self._anomaly(
                waybill_id,
                f"low_confidence_{key}",
                "warning",
                f"Поле {key} распознано с низкой уверенностью.",
                {
                    "value": item["value"],
                    "confidence": item["confidence"],
                },
            )
        if vehicle_id is None:
            self._anomaly(
                waybill_id,
                "unknown_vehicle",
                "error",
                "Автомобиль не найден в справочнике гаража.",
                {"plate": self._value(fields, "vehicle_plate")},
            )
        if employee_id is None:
            self._anomaly(
                waybill_id,
                "unknown_driver",
                "error",
                "Водитель не найден в справочнике сотрудников.",
                {"driver": self._value(fields, "driver_name")},
            )

        odometer_start = self._number_value(fields, "odometer_start")
        odometer_end = self._number_value(fields, "odometer_end")
        if (
            odometer_start is not None
            and odometer_end is not None
            and odometer_end < odometer_start
        ):
            self._anomaly(
                waybill_id,
                "odometer_reversed",
                "error",
                "Конечный одометр меньше начального.",
                {
                    "start": odometer_start,
                    "end": odometer_end,
                },
            )

        fuel_open = self._number_value(fields, "fuel_open_l")
        fuel_close = self._number_value(fields, "fuel_close_l")
        for name, value in (
            ("fuel_open_l", fuel_open),
            ("fuel_close_l", fuel_close),
        ):
            if value is not None and value < 0:
                self._anomaly(
                    waybill_id,
                    "negative_fuel",
                    "error",
                    f"Отрицательный остаток топлива: {name}.",
                    {"field": name, "value": value},
                )

        waybill = self.waybill(waybill_id)
        if (
            waybill.get("distance_km", 0) == 0
            and (
                waybill.get("route")
                or waybill.get("assignment_text")
            )
        ):
            self._anomaly(
                waybill_id,
                "zero_mileage_with_trip",
                "warning",
                "Есть маршрут/задание, но пробег равен нулю.",
                {},
            )

        if waybill.get("departure_time") and waybill.get("return_time"):
            duration = self._actual_interval_minutes(
                waybill["trip_date"],
                waybill["departure_time"],
                waybill["return_time"],
            )
            if duration is not None and duration > 24 * 60:
                self._anomaly(
                    waybill_id,
                    "impossible_duration",
                    "error",
                    "Продолжительность путевого листа превышает 24 часа.",
                    {"minutes": duration},
                )

        card = waybill.get("fuel_card_number") or ""
        if card and employee_id and waybill.get("trip_date"):
            owner = self.garage._employee_for_card(card, waybill["trip_date"])
            if owner and owner != employee_id:
                self._anomaly(
                    waybill_id,
                    "fuel_card_driver_mismatch",
                    "error",
                    "Топливная карта закреплена за другим сотрудником.",
                    {
                        "recognized_employee_id": employee_id,
                        "card_employee_id": owner,
                        "card_number": card,
                    },
                )

        vehicle = (
            self.garage.vehicle(vehicle_id)
            if vehicle_id
            else None
        )
        if vehicle:
            recognized_make = (
                (waybill.get("vehicle_make") or "") + " " +
                (waybill.get("vehicle_model") or "")
            ).strip().upper()
            actual_make = (
                (vehicle.get("make") or "") + " " +
                (vehicle.get("model") or "")
            ).strip().upper()
            if recognized_make and actual_make:
                words = set(re.findall(r"[A-ZА-ЯЁ0-9]+", recognized_make))
                actual_words = set(re.findall(r"[A-ZА-ЯЁ0-9]+", actual_make))
                if words and actual_words and not (words & actual_words):
                    self._anomaly(
                        waybill_id,
                        "vehicle_make_mismatch",
                        "warning",
                        "Марка/модель в путевом листе не совпадает с карточкой машины.",
                        {
                            "recognized": recognized_make,
                            "garage": actual_make,
                        },
                    )

    def validate_batch(self, batch_id: str) -> dict:
        waybills = self.db.query(
            """
            SELECT *
            FROM garage_waybills
            WHERE batch_id=?
            ORDER BY COALESCE(trip_date, ''), created_at
            """,
            (batch_id,),
        )
        by_vehicle: dict[str, list[dict]] = {}
        by_driver: dict[str, list[dict]] = {}
        for item in waybills:
            if item.get("vehicle_id"):
                by_vehicle.setdefault(item["vehicle_id"], []).append(item)
            if item.get("employee_id"):
                by_driver.setdefault(item["employee_id"], []).append(item)

        for vehicle_id, rows in by_vehicle.items():
            rows.sort(key=lambda item: (item.get("trip_date") or "", item["created_at"]))
            previous = None
            for current in rows:
                if previous is not None:
                    prev_end = previous.get("odometer_end")
                    current_start = current.get("odometer_start")
                    if prev_end is not None and current_start is not None:
                        delta = round(float(current_start) - float(prev_end), 3)
                        if abs(delta) > 1.0:
                            self._anomaly(
                                current["id"],
                                "odometer_sequence_gap",
                                "warning",
                                "Начальный одометр не совпадает с концом предыдущего путевого листа.",
                                {
                                    "previous_waybill_id": previous["id"],
                                    "previous_end": prev_end,
                                    "current_start": current_start,
                                    "difference": delta,
                                },
                            )
                previous = current

        for employee_id, rows in by_driver.items():
            rows.sort(key=lambda item: (item.get("trip_date") or "", item.get("departure_time") or ""))
            for index, left in enumerate(rows):
                for right in rows[index + 1:]:
                    if left.get("trip_date") != right.get("trip_date"):
                        break
                    if self._intervals_overlap(left, right):
                        self._anomaly(
                            right["id"],
                            "driver_waybill_overlap",
                            "error",
                            "Путевые листы одного водителя пересекаются по времени.",
                            {
                                "other_waybill_id": left["id"],
                                "other_vehicle_id": left.get("vehicle_id"),
                            },
                        )
                    if (
                        left.get("vehicle_id")
                        and right.get("vehicle_id")
                        and left["vehicle_id"] != right["vehicle_id"]
                        and self._intervals_overlap(left, right)
                    ):
                        self._anomaly(
                            right["id"],
                            "driver_two_vehicles_same_time",
                            "error",
                            "Водитель одновременно указан на двух автомобилях.",
                            {
                                "other_waybill_id": left["id"],
                                "vehicle_ids": [
                                    left["vehicle_id"],
                                    right["vehicle_id"],
                                ],
                            },
                        )

        for item in waybills:
            anomalies = self.anomalies(item["id"])
            if any(not a["resolved"] for a in anomalies):
                self.db.execute(
                    """
                    UPDATE garage_waybills
                    SET needs_review=1, processing_status='needs_review',
                        updated_at=?
                    WHERE id=?
                    """,
                    (_now(), item["id"]),
                )
        return {
            "batch_id": batch_id,
            "waybills": len(waybills),
            "anomalies": sum(len(self.anomalies(item["id"])) for item in waybills),
        }

    def _validate_fuel_transactions_for_batch(self, batch_id: str) -> None:
        waybills = self.db.query(
            "SELECT * FROM garage_waybills WHERE batch_id=?",
            (batch_id,),
        )
        for waybill in waybills:
            if not waybill.get("trip_date"):
                continue
            transactions = self.db.query(
                """
                SELECT *
                FROM garage_fuel_transactions
                WHERE operation_date=?
                  AND (
                    (? IS NOT NULL AND employee_id=?)
                    OR (? IS NOT NULL AND vehicle_id=?)
                    OR (?!='' AND card_number=?)
                  )
                ORDER BY operation_time
                """,
                (
                    waybill["trip_date"],
                    waybill.get("employee_id"),
                    waybill.get("employee_id"),
                    waybill.get("vehicle_id"),
                    waybill.get("vehicle_id"),
                    waybill.get("fuel_card_number") or "",
                    waybill.get("fuel_card_number") or "",
                ),
            )
            recognized_refuel = float(waybill.get("refueled_l") or 0)
            statement_liters = round(
                sum(float(item.get("quantity_l") or 0) for item in transactions),
                4,
            )
            if recognized_refuel > 0 and not transactions:
                self._anomaly(
                    waybill["id"],
                    "refuel_not_found_in_statement",
                    "warning",
                    "Заправка указана в путевом листе, но не найдена в выписке ГСМ.",
                    {"waybill_refueled_l": recognized_refuel},
                )
            if transactions and recognized_refuel > 0 and abs(statement_liters - recognized_refuel) > 2.0:
                self._anomaly(
                    waybill["id"],
                    "refuel_volume_mismatch",
                    "warning",
                    "Литры по выписке отличаются от заправки в путевом листе.",
                    {
                        "statement_liters": statement_liters,
                        "waybill_liters": recognized_refuel,
                    },
                )
            for tx in transactions:
                if float(tx.get("quantity_l") or 0) > 120:
                    self._anomaly(
                        waybill["id"],
                        "suspicious_refuel_volume",
                        "warning",
                        "Подозрительно большой объём одной заправки.",
                        {
                            "transaction_id": tx["id"],
                            "quantity_l": tx["quantity_l"],
                        },
                    )

        # Statement transaction without a matching waybill on the same day.
        batch_dates = {
            item["trip_date"] for item in waybills if item.get("trip_date")
        }
        if not batch_dates:
            return
        placeholders = ",".join("?" for _ in batch_dates)
        transactions = self.db.query(
            f"""
            SELECT *
            FROM garage_fuel_transactions
            WHERE operation_date IN ({placeholders})
            """,
            tuple(sorted(batch_dates)),
        )
        for tx in transactions:
            candidates = [
                item for item in waybills
                if item.get("trip_date") == tx["operation_date"]
                and (
                    (tx.get("employee_id") and item.get("employee_id") == tx["employee_id"])
                    or (tx.get("vehicle_id") and item.get("vehicle_id") == tx["vehicle_id"])
                    or (
                        tx.get("card_number")
                        and item.get("fuel_card_number")
                        and tx["card_number"] == item["fuel_card_number"]
                    )
                )
            ]
            if not candidates:
                # Attach the anomaly to a same-date waybill when one exists;
                # otherwise it remains visible through fuel unresolved views.
                same_date = [
                    item for item in waybills
                    if item.get("trip_date") == tx["operation_date"]
                ]
                if same_date:
                    self._anomaly(
                        same_date[0]["id"],
                        "statement_refuel_without_waybill",
                        "warning",
                        "Выписка содержит заправку без подходящего путевого листа.",
                        {
                            "transaction_id": tx["id"],
                            "card_number": tx.get("card_number"),
                            "quantity_l": tx.get("quantity_l"),
                        },
                    )

    # --------------------------------------------------------------- overtime

    def save_schedule(self, payload: dict) -> dict:
        employee_id = str(payload.get("employee_id") or "").strip()
        self._employee(employee_id)
        start_time = str(payload.get("start_time") or "").strip()
        end_time = str(payload.get("end_time") or "").strip()
        if not _parse_clock(start_time) or not _parse_clock(end_time):
            raise ValueError("start_time and end_time must use HH:MM")
        weekdays = payload.get("weekdays", [0, 1, 2, 3, 4])
        if not isinstance(weekdays, list) or not weekdays:
            raise ValueError("weekdays must be a non-empty array")
        normalized_weekdays = sorted({int(day) for day in weekdays})
        if any(day < 0 or day > 6 for day in normalized_weekdays):
            raise ValueError("weekday must be between 0 and 6")
        valid_from = str(payload.get("valid_from") or "").strip() or None
        valid_to = str(payload.get("valid_to") or "").strip() or None
        schedule_id = str(payload.get("id") or "").strip() or str(uuid4())
        now = _now()

        current = self.db.query(
            """
            SELECT id
            FROM work_employee_schedules
            WHERE employee_id=? AND active=1
            ORDER BY created_at DESC
            """,
            (employee_id,),
        )
        with self.db.connect() as db:
            for item in current:
                if item["id"] != schedule_id:
                    db.execute(
                        """
                        UPDATE work_employee_schedules
                        SET active=0, valid_to=COALESCE(valid_to, ?), updated_at=?
                        WHERE id=?
                        """,
                        (valid_from, now, item["id"]),
                    )
            db.execute(
                """
                INSERT INTO work_employee_schedules(
                    id, employee_id, valid_from, valid_to, weekdays_json,
                    start_time, end_time, source, active, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    valid_from=excluded.valid_from,
                    valid_to=excluded.valid_to,
                    weekdays_json=excluded.weekdays_json,
                    start_time=excluded.start_time,
                    end_time=excluded.end_time,
                    source=excluded.source,
                    active=1,
                    updated_at=excluded.updated_at
                """,
                (
                    schedule_id,
                    employee_id,
                    valid_from,
                    valid_to,
                    _json(normalized_weekdays),
                    start_time,
                    end_time,
                    str(payload.get("source") or "manual"),
                    now,
                    now,
                ),
            )
        self._audit(
            actor=str(payload.get("actor") or "user"),
            action="employee_schedule_saved",
            entity_type="employee",
            entity_id=employee_id,
            new_value=f"{start_time}-{end_time}",
            reason="schedule_configuration",
            source=str(payload.get("source") or "manual"),
        )
        return self.schedule_for(employee_id, valid_from or date.today().isoformat()) or {}

    def schedules(self, employee_id: str | None = None) -> list[dict]:
        clauses = []
        params: list = []
        if employee_id:
            clauses.append("employee_id=?")
            params.append(employee_id)
        sql = "SELECT * FROM work_employee_schedules"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY employee_id, active DESC, created_at DESC"
        rows = self.db.query(sql, tuple(params))
        for item in rows:
            item["active"] = bool(item["active"])
            item["weekdays"] = json.loads(item.pop("weekdays_json") or "[]")
        return rows

    def schedule_for(self, employee_id: str, work_date: str) -> dict | None:
        rows = self.db.query(
            """
            SELECT *
            FROM work_employee_schedules
            WHERE employee_id=?
              AND (valid_from IS NULL OR valid_from<=?)
              AND (valid_to IS NULL OR valid_to>=?)
            ORDER BY active DESC, COALESCE(valid_from, '') DESC, created_at DESC
            LIMIT 10
            """,
            (employee_id, work_date, work_date),
        )
        weekday = date.fromisoformat(work_date).weekday()
        for item in rows:
            weekdays = json.loads(item["weekdays_json"] or "[]")
            if weekday not in weekdays:
                continue
            item = dict(item)
            item["active"] = bool(item["active"])
            item["weekdays"] = weekdays
            item.pop("weekdays_json", None)
            return item
        return None

    def _build_overtime_candidate(self, waybill_id: str) -> dict | None:
        waybill = self.waybill(waybill_id)
        if not (
            waybill.get("employee_id")
            and waybill.get("trip_date")
            and waybill.get("departure_time")
            and waybill.get("return_time")
        ):
            return None
        schedule = self.schedule_for(
            waybill["employee_id"],
            waybill["trip_date"],
        )
        if not schedule:
            return self._upsert_overtime_candidate(
                waybill,
                schedule=None,
                before=0,
                after=0,
                confidence=min(float(waybill.get("confidence") or 0), 0.6),
                status="needs_review",
                comment="Не задан точный график начала/окончания рабочего дня.",
            )

        interval = self._actual_datetimes(waybill)
        if interval is None:
            return None
        actual_start, actual_end = interval
        schedule_start, schedule_end = self._schedule_datetimes(
            waybill["trip_date"],
            schedule["start_time"],
            schedule["end_time"],
        )
        before = max(
            0,
            int(
                (
                    min(actual_end, schedule_start) - actual_start
                ).total_seconds()
                // 60
            )
            if actual_start < schedule_start
            else 0,
        )
        after_start = max(actual_start, schedule_end)
        after = max(
            0,
            int((actual_end - after_start).total_seconds() // 60)
            if actual_end > schedule_end
            else 0,
        )
        total = before + after
        if total <= 0:
            status = "detected"
            comment = "Возможная переработка по времени путевого листа не обнаружена."
        else:
            status = "detected"
            comment = (
                "Предварительная переработка. Требуется подтверждение человеком; "
                "время путевого листа не является юридически подтверждённой "
                "сверхурочной работой."
            )
        confidence = min(
            float(waybill.get("confidence") or 0),
            self._field_confidence(waybill_id, "departure_time"),
            self._field_confidence(waybill_id, "return_time"),
        )
        if confidence < FIELD_THRESHOLD:
            status = "needs_review"
        return self._upsert_overtime_candidate(
            waybill,
            schedule=schedule,
            before=before,
            after=after,
            confidence=confidence,
            status=status,
            comment=comment,
        )

    def _upsert_overtime_candidate(
        self,
        waybill: dict,
        *,
        schedule: dict | None,
        before: int,
        after: int,
        confidence: float,
        status: str,
        comment: str,
    ) -> dict:
        existing = self.db.query(
            "SELECT id, status, applied_minutes FROM work_overtime_candidates WHERE waybill_id=?",
            (waybill["id"],),
        )
        candidate_id = existing[0]["id"] if existing else str(uuid4())
        current_status = existing[0]["status"] if existing else None
        if current_status in {"approved", "rejected", "applied_to_timesheet"}:
            return self.overtime_candidate(candidate_id)

        now = _now()
        self.db.execute(
            """
            INSERT INTO work_overtime_candidates(
                id, employee_id, work_date, waybill_id,
                scheduled_start, scheduled_end, actual_departure,
                actual_return, overtime_before_minutes,
                overtime_after_minutes, overtime_total_minutes,
                status, confidence, comment, applied_entry_id,
                applied_minutes, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)
            ON CONFLICT(waybill_id) DO UPDATE SET
                employee_id=excluded.employee_id,
                work_date=excluded.work_date,
                scheduled_start=excluded.scheduled_start,
                scheduled_end=excluded.scheduled_end,
                actual_departure=excluded.actual_departure,
                actual_return=excluded.actual_return,
                overtime_before_minutes=excluded.overtime_before_minutes,
                overtime_after_minutes=excluded.overtime_after_minutes,
                overtime_total_minutes=excluded.overtime_total_minutes,
                status=excluded.status,
                confidence=excluded.confidence,
                comment=excluded.comment,
                updated_at=excluded.updated_at
            """,
            (
                candidate_id,
                waybill["employee_id"],
                waybill["trip_date"],
                waybill["id"],
                schedule["start_time"] if schedule else None,
                schedule["end_time"] if schedule else None,
                waybill["departure_time"],
                waybill["return_time"],
                int(before),
                int(after),
                int(before + after),
                status,
                round(float(confidence), 4),
                comment,
                now,
                now,
            ),
        )
        return self.overtime_candidate(candidate_id)

    def overtime_candidate(self, candidate_id: str) -> dict:
        rows = self.db.query(
            """
            SELECT c.*, e.full_name, e.personnel_number,
                   w.waybill_number, w.trip_date, w.source_document_id,
                   v.registration_number
            FROM work_overtime_candidates c
            LEFT JOIN work_employees e ON e.id=c.employee_id
            JOIN garage_waybills w ON w.id=c.waybill_id
            LEFT JOIN garage_vehicles v ON v.id=w.vehicle_id
            WHERE c.id=?
            """,
            (candidate_id,),
        )
        if not rows:
            raise KeyError(candidate_id)
        item = dict(rows[0])
        item["overtime_before"] = _minutes_hhmm(item["overtime_before_minutes"])
        item["overtime_after"] = _minutes_hhmm(item["overtime_after_minutes"])
        item["overtime_total"] = _minutes_hhmm(item["overtime_total_minutes"])
        return item

    def overtime_candidates(
        self,
        *,
        month: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        clauses = []
        params: list = []
        if month:
            year, month_no = map(int, month.split("-"))
            start = date(year, month_no, 1)
            last = calendar.monthrange(year, month_no)[1]
            end = date(year, month_no, last)
            clauses.append("c.work_date BETWEEN ? AND ?")
            params.extend([start.isoformat(), end.isoformat()])
        if status:
            clauses.append("c.status=?")
            params.append(status)
        sql = """
            SELECT c.id
            FROM work_overtime_candidates c
        """
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY c.work_date DESC, c.created_at DESC"
        return [
            self.overtime_candidate(row["id"])
            for row in self.db.query(sql, tuple(params))
        ]

    def review_overtime(
        self,
        candidate_id: str,
        *,
        action: str,
        actor: str = "user",
        corrected_total_minutes: int | None = None,
        comment: str = "",
    ) -> dict:
        candidate = self.overtime_candidate(candidate_id)
        action = str(action or "").strip().lower()
        now = _now()

        if action == "reject":
            self.db.execute(
                """
                UPDATE work_overtime_candidates
                SET status='rejected', comment=?, updated_at=?
                WHERE id=?
                """,
                (comment or candidate["comment"], now, candidate_id),
            )
            self._audit(
                actor=actor,
                action="overtime_rejected",
                entity_type="overtime_candidate",
                entity_id=candidate_id,
                original_value=str(candidate["overtime_total_minutes"]),
                new_value="0",
                reason=comment or "human_rejected",
                source="timesheet_review",
                source_document_id=candidate.get("source_document_id"),
            )
            return self.overtime_candidate(candidate_id)

        if action == "correct":
            if corrected_total_minutes is None or int(corrected_total_minutes) < 0:
                raise ValueError("corrected_total_minutes must be >= 0")
            corrected = int(corrected_total_minutes)
            self.db.execute(
                """
                UPDATE work_overtime_candidates
                SET overtime_before_minutes=0,
                    overtime_after_minutes=?,
                    overtime_total_minutes=?,
                    status='needs_review',
                    comment=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    corrected,
                    corrected,
                    comment or "Исправлено пользователем; требуется подтверждение.",
                    now,
                    candidate_id,
                ),
            )
            self._audit(
                actor=actor,
                action="overtime_corrected",
                entity_type="overtime_candidate",
                entity_id=candidate_id,
                field_name="overtime_total_minutes",
                original_value=str(candidate["overtime_total_minutes"]),
                new_value=str(corrected),
                reason=comment or "human_correction",
                source="timesheet_review",
                source_document_id=candidate.get("source_document_id"),
            )
            return self.overtime_candidate(candidate_id)

        if action != "approve":
            raise ValueError("action must be approve, correct or reject")

        self.db.execute(
            """
            UPDATE work_overtime_candidates
            SET status='approved', comment=?, updated_at=?
            WHERE id=?
            """,
            (comment or candidate["comment"], now, candidate_id),
        )
        applied = self._apply_overtime(candidate_id)
        self._audit(
            actor=actor,
            action="overtime_approved_and_applied",
            entity_type="overtime_candidate",
            entity_id=candidate_id,
            original_value=str(candidate["overtime_total_minutes"]),
            new_value=str(applied["overtime_total_minutes"]),
            reason=comment or "human_approved",
            source="timesheet_review",
            source_document_id=applied.get("source_document_id"),
        )
        return applied

    def _apply_overtime(self, candidate_id: str) -> dict:
        candidate = self.overtime_candidate(candidate_id)
        if not candidate.get("employee_id") or not candidate.get("work_date"):
            raise ValueError("candidate has no employee/date")

        minutes = int(candidate["overtime_total_minutes"] or 0)
        hours = round(minutes / 60.0, 2)
        existing = self.db.query(
            """
            SELECT *
            FROM work_timesheet_entries
            WHERE employee_id=? AND work_date=?
            """,
            (candidate["employee_id"], candidate["work_date"]),
        )
        previous_applied = int(candidate.get("applied_minutes") or 0)
        delta_hours = round((minutes - previous_applied) / 60.0, 2)

        if existing:
            entry = existing[0]
            current = float(entry["overtime_hours"] or 0)
            new_overtime = max(0.0, round(current + delta_hours, 2))
            self.db.execute(
                """
                UPDATE work_timesheet_entries
                SET overtime_hours=?, source='waybill_confirmed', updated_at=?
                WHERE id=?
                """,
                (new_overtime, _now(), entry["id"]),
            )
            entry_id = entry["id"]
        else:
            work_day = date.fromisoformat(candidate["work_date"])
            planned = self.timesheet.default_planned_hours(
                candidate["employee_id"],
                work_day,
            )
            entry = self.timesheet.save_entry({
                "employee_id": candidate["employee_id"],
                "work_date": candidate["work_date"],
                "status": "work",
                "planned_hours": planned,
                "actual_hours": planned,
                "overtime_hours": hours,
                "night_hours": 0,
                "note": (
                    f"Подтверждённая возможная переработка по путевому листу "
                    f"№{candidate.get('waybill_number') or candidate['waybill_id']}"
                ),
                "source": "waybill_confirmed",
            })
            entry_id = entry["id"]

        self.db.execute(
            """
            UPDATE work_overtime_candidates
            SET status='applied_to_timesheet', applied_entry_id=?,
                applied_minutes=?, updated_at=?
            WHERE id=?
            """,
            (entry_id, minutes, _now(), candidate_id),
        )
        return self.overtime_candidate(candidate_id)

    def overtime_month_summary(self, month: str) -> dict:
        items = self.overtime_candidates(month=month)
        grouped: dict[str, dict] = {}
        for item in items:
            employee_id = item.get("employee_id") or "unknown"
            row = grouped.setdefault(employee_id, {
                "employee_id": item.get("employee_id"),
                "full_name": item.get("full_name") or "Не определён",
                "waybills": 0,
                "days_with_candidate": set(),
                "before_minutes": 0,
                "after_minutes": 0,
                "preliminary_minutes": 0,
                "approved_minutes": 0,
                "rejected_minutes": 0,
                "items": [],
            })
            row["waybills"] += 1
            if item.get("work_date") and item["overtime_total_minutes"] > 0:
                row["days_with_candidate"].add(item["work_date"])
            row["before_minutes"] += int(item["overtime_before_minutes"] or 0)
            row["after_minutes"] += int(item["overtime_after_minutes"] or 0)
            row["preliminary_minutes"] += int(item["overtime_total_minutes"] or 0)
            if item["status"] in {"approved", "applied_to_timesheet"}:
                row["approved_minutes"] += int(item["overtime_total_minutes"] or 0)
            if item["status"] == "rejected":
                row["rejected_minutes"] += int(item["overtime_total_minutes"] or 0)
            row["items"].append(item)

        result = []
        for row in grouped.values():
            row["days_with_candidate"] = len(row["days_with_candidate"])
            for key in (
                "before_minutes",
                "after_minutes",
                "preliminary_minutes",
                "approved_minutes",
                "rejected_minutes",
            ):
                row[key.removesuffix("_minutes")] = _minutes_hhmm(row[key])
            result.append(row)
        result.sort(key=lambda item: item["full_name"])
        return {"month": month, "employees": result}

    # ----------------------------------------------------------- human review

    FIELD_COLUMN_MAP = {
        "waybill_number": "waybill_number",
        "trip_date": "trip_date",
        "vehicle_plate": None,
        "driver_name": "driver_name",
        "personnel_number": "personnel_number",
        "departure_time": "departure_time",
        "return_time": "return_time",
        "odometer_start": "odometer_start",
        "odometer_end": "odometer_end",
        "fuel_open_l": "fuel_open_l",
        "fuel_close_l": "fuel_close_l",
        "fuel_issued_l": "fuel_issued_l",
        "refueled_l": "refueled_l",
        "fuel_name": "fuel_name",
        "route": "route",
        "assignment_text": "assignment_text",
        "fuel_card_number": "fuel_card_number",
        "organization": "organization",
        "department": "department",
        "vehicle_vin": "vehicle_vin",
        "garage_number": "garage_number",
    }

    def correct_field(
        self,
        waybill_id: str,
        *,
        field_key: str,
        corrected_value: str,
        actor: str = "user",
        reason: str = "",
    ) -> dict:
        if field_key not in self.FIELD_COLUMN_MAP:
            raise ValueError("unsupported waybill field")
        rows = self.db.query(
            """
            SELECT original_value, corrected_value
            FROM garage_waybill_fields
            WHERE waybill_id=? AND field_key=?
            """,
            (waybill_id, field_key),
        )
        if not rows:
            raise KeyError(field_key)
        old = rows[0]["corrected_value"]
        if old is None:
            old = rows[0]["original_value"]
        now = _now()
        self.db.execute(
            """
            UPDATE garage_waybill_fields
            SET corrected_value=?, verified=1, corrected_at=?,
                corrected_by=?, updated_at=?
            WHERE waybill_id=? AND field_key=?
            """,
            (
                str(corrected_value),
                now,
                actor,
                now,
                waybill_id,
                field_key,
            ),
        )
        column = self.FIELD_COLUMN_MAP[field_key]
        if column:
            value = corrected_value
            if field_key in {
                "odometer_start",
                "odometer_end",
                "fuel_open_l",
                "fuel_close_l",
                "fuel_issued_l",
                "refueled_l",
            }:
                value = float(str(corrected_value).replace(",", "."))
            self.db.execute(
                f"UPDATE garage_waybills SET {column}=?, updated_at=? WHERE id=?",
                (value, now, waybill_id),
            )

        self._audit(
            actor=actor,
            action="waybill_field_corrected",
            entity_type="waybill",
            entity_id=waybill_id,
            field_name=field_key,
            original_value=str(old),
            new_value=str(corrected_value),
            reason=reason or "ocr_correction",
            source="waybill_review",
            source_document_id=waybill_id,
        )
        self._relink_after_correction(waybill_id, field_key, corrected_value)
        self._recalculate_waybill(waybill_id)
        self._build_overtime_candidate(waybill_id)
        return self.waybill(waybill_id)

    def confirm_waybill(
        self,
        waybill_id: str,
        *,
        actor: str = "user",
        comment: str = "",
    ) -> dict:
        waybill = self.waybill(waybill_id)
        missing = []
        if not waybill.get("trip_date"):
            missing.append("дата")
        if not waybill.get("vehicle_id"):
            missing.append("автомобиль")
        if not waybill.get("employee_id"):
            missing.append("водитель")
        if missing:
            raise ValueError(
                "Нельзя подтвердить путевой лист: требуется определить "
                + ", ".join(missing)
            )

        self.db.execute(
            """
            UPDATE garage_waybill_fields
            SET verified=1, updated_at=?
            WHERE waybill_id=? AND COALESCE(corrected_value, original_value)!=''
            """,
            (_now(), waybill_id),
        )
        self.db.execute(
            """
            UPDATE garage_waybills
            SET needs_review=0, processing_status='confirmed', updated_at=?
            WHERE id=?
            """,
            (_now(), waybill_id),
        )
        self._audit(
            actor=actor,
            action="waybill_confirmed",
            entity_type="waybill",
            entity_id=waybill_id,
            new_value="confirmed",
            reason=comment or "human_review",
            source="waybill_review",
            source_document_id=waybill_id,
        )
        return self.waybill(waybill_id)

    # ------------------------------------------------------------- data access

    def batch(self, batch_id: str) -> dict:
        rows = self.db.query(
            "SELECT * FROM work_waybill_batches WHERE id=?",
            (batch_id,),
        )
        if not rows:
            raise KeyError(batch_id)
        item = dict(rows[0])
        item["progress"] = json.loads(item.pop("progress_json") or "{}")
        return item

    def batches(self, limit: int = 50) -> list[dict]:
        rows = self.db.query(
            """
            SELECT *
            FROM work_waybill_batches
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 200)),),
        )
        result = []
        for item in rows:
            item["progress"] = json.loads(item.pop("progress_json") or "{}")
            result.append(item)
        return result

    def batch_pages(self, batch_id: str) -> list[dict]:
        rows = self.db.query(
            """
            SELECT page_number, waybill_id, ocr_engine, ocr_text,
                   ocr_blocks_json, ocr_tables_json, confidence,
                   image_path, status, error
            FROM work_waybill_batch_pages
            WHERE batch_id=?
            ORDER BY page_number
            """,
            (batch_id,),
        )
        for item in rows:
            item["blocks"] = json.loads(item.pop("ocr_blocks_json") or "[]")
            item["tables"] = json.loads(item.pop("ocr_tables_json") or "[]")
        return rows

    def waybill(self, waybill_id: str) -> dict:
        rows = self.db.query(
            """
            SELECT w.*, e.full_name, e.personnel_number AS linked_personnel_number,
                   v.registration_number, v.make AS garage_make,
                   v.model AS garage_model,
                   v.vin AS garage_vin
            FROM garage_waybills w
            LEFT JOIN work_employees e ON e.id=w.employee_id
            LEFT JOIN garage_vehicles v ON v.id=w.vehicle_id
            WHERE w.id=?
            """,
            (waybill_id,),
        )
        if not rows:
            raise KeyError(waybill_id)
        item = dict(rows[0])
        item["needs_review"] = bool(item["needs_review"])
        item["source_pages"] = json.loads(item.pop("source_pages_json") or "[]")
        item["fields"] = self.waybill_fields(waybill_id)
        item["anomalies"] = self.anomalies(waybill_id)
        candidate = self.db.query(
            "SELECT id FROM work_overtime_candidates WHERE waybill_id=?",
            (waybill_id,),
        )
        item["overtime_candidate"] = (
            self.overtime_candidate(candidate[0]["id"])
            if candidate
            else None
        )
        return item

    def waybills(
        self,
        *,
        month: str | None = None,
        batch_id: str | None = None,
        needs_review: bool | None = None,
        limit: int = 500,
    ) -> list[dict]:
        clauses = []
        params: list = []
        if month:
            year, month_no = map(int, month.split("-"))
            start = date(year, month_no, 1)
            end = date(year, month_no, calendar.monthrange(year, month_no)[1])
            clauses.append("trip_date BETWEEN ? AND ?")
            params.extend([start.isoformat(), end.isoformat()])
        if batch_id:
            clauses.append("batch_id=?")
            params.append(batch_id)
        if needs_review is not None:
            clauses.append("needs_review=?")
            params.append(1 if needs_review else 0)
        sql = "SELECT id FROM garage_waybills"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY COALESCE(trip_date, '') DESC, created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 2000)))
        return [
            self.waybill(row["id"])
            for row in self.db.query(sql, tuple(params))
        ]

    def waybill_fields(self, waybill_id: str) -> list[dict]:
        rows = self.db.query(
            """
            SELECT field_key, original_value, corrected_value, confidence,
                   verified, provenance_json, corrected_at, corrected_by,
                   updated_at
            FROM garage_waybill_fields
            WHERE waybill_id=?
            ORDER BY field_key
            """,
            (waybill_id,),
        )
        for item in rows:
            item["verified"] = bool(item["verified"])
            item["value"] = (
                item["corrected_value"]
                if item["corrected_value"] is not None
                else item["original_value"]
            )
            item["provenance"] = json.loads(item.pop("provenance_json") or "{}")
        return rows

    def anomalies(self, waybill_id: str) -> list[dict]:
        rows = self.db.query(
            """
            SELECT id, anomaly_type, severity, message, details_json,
                   resolved, created_at, updated_at
            FROM garage_waybill_anomalies
            WHERE waybill_id=?
            ORDER BY resolved ASC,
                     CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                     created_at DESC
            """,
            (waybill_id,),
        )
        for item in rows:
            item["resolved"] = bool(item["resolved"])
            item["details"] = json.loads(item.pop("details_json") or "{}")
        return rows

    def batch_summary(self, batch_id: str) -> dict:
        waybills = self.db.query(
            "SELECT * FROM garage_waybills WHERE batch_id=?",
            (batch_id,),
        )
        batch = self.batch(batch_id)
        vehicles = {
            item["vehicle_id"] for item in waybills if item.get("vehicle_id")
        }
        employees = {
            item["employee_id"] for item in waybills if item.get("employee_id")
        }
        needs_review = sum(bool(item["needs_review"]) for item in waybills)
        anomalies = 0
        overtime = 0
        for item in waybills:
            anomalies += len([
                a for a in self.anomalies(item["id"])
                if not a["resolved"]
            ])
            candidate = self.db.query(
                """
                SELECT overtime_total_minutes
                FROM work_overtime_candidates
                WHERE waybill_id=?
                """,
                (item["id"],),
            )
            if candidate and int(candidate[0]["overtime_total_minutes"] or 0) > 0:
                overtime += 1
        return {
            "batch_id": batch_id,
            "pdfs": 1 if Path(batch["original_name"]).suffix.lower() == ".pdf" else 0,
            "pages": int(batch["page_count"] or 0),
            "waybills": len(waybills),
            "vehicles": len(vehicles),
            "drivers": len(employees),
            "processed_ok": len(waybills) - needs_review,
            "needs_review": needs_review,
            "fuel_records": len(waybills),
            "overtime_candidates": overtime,
            "anomalies": anomalies,
            "errors": int(batch["errors_count"] or 0),
        }

    def audit(self, *, entity_type: str | None = None, entity_id: str | None = None, limit: int = 200) -> list[dict]:
        clauses = []
        params: list = []
        if entity_type:
            clauses.append("entity_type=?")
            params.append(entity_type)
        if entity_id:
            clauses.append("entity_id=?")
            params.append(entity_id)
        sql = "SELECT * FROM work_audit_log"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        return self.db.query(sql, tuple(params))

    # --------------------------------------------------------------- internals

    def _set_batch(self, batch_id: str, **values) -> None:
        allowed = {
            "document_id",
            "page_count",
            "status",
            "stage",
            "pages_processed",
            "pages_ocr",
            "waybills_detected",
            "waybills_completed",
            "errors_count",
            "review_count",
            "error",
        }
        updates = []
        params = []
        progress = values.pop("progress", None)
        for key, value in values.items():
            if key not in allowed:
                raise ValueError(f"unsupported batch field {key}")
            updates.append(f"{key}=?")
            params.append(value)
        if progress is not None:
            current = self.batch(batch_id).get("progress", {})
            merged = {**current, **progress}
            updates.append("progress_json=?")
            params.append(_json(merged))
        if not updates:
            return
        updates.append("updated_at=?")
        params.append(_now())
        params.append(batch_id)
        self.db.execute(
            f"UPDATE work_waybill_batches SET {', '.join(updates)} WHERE id=?",
            tuple(params),
        )

    def _record_batch_error(self, batch_id: str, message: str) -> None:
        batch = self.batch(batch_id)
        errors = list(batch.get("progress", {}).get("errors", []))
        errors.append(message)
        self._set_batch(
            batch_id,
            progress={"errors": errors[-50:]},
        )

    def _employee(self, employee_id: str) -> dict:
        rows = self.db.query(
            """
            SELECT id, personnel_number, full_name, department, position,
                   schedule_type, weekly_hours, active
            FROM work_employees
            WHERE id=?
            """,
            (employee_id,),
        )
        if not rows:
            raise KeyError(employee_id)
        return rows[0]

    @staticmethod
    def _value(fields: dict, key: str) -> str:
        item = fields.get(key)
        return str(item.get("value") or "").strip() if item else ""

    @staticmethod
    def _number_value(fields: dict, key: str) -> float | None:
        raw = WaybillAutomationService._value(fields, key)
        if not raw:
            return None
        try:
            return float(raw.replace(",", "."))
        except ValueError:
            return None

    @staticmethod
    def _distance(start: float | None, end: float | None) -> float | None:
        if start is None or end is None:
            return None
        if end < start:
            return 0.0
        return round(end - start, 3)

    @staticmethod
    def _vehicle_make(fields: dict, vehicle: dict | None) -> str:
        text = WaybillAutomationService._value(fields, "vehicle_make_model")
        if text:
            return text.split()[0] if text.split() else ""
        return str(vehicle.get("make") or "") if vehicle else ""

    @staticmethod
    def _vehicle_model(fields: dict, vehicle: dict | None) -> str:
        text = WaybillAutomationService._value(fields, "vehicle_make_model")
        if text:
            parts = text.split()
            return " ".join(parts[1:]) if len(parts) > 1 else ""
        return str(vehicle.get("model") or "") if vehicle else ""

    @staticmethod
    def _waybill_title(
        trip_date: str,
        number: str,
        plate: str,
        driver: str,
        sequence: int,
    ) -> str:
        chunks = ["Путевой лист"]
        if number:
            chunks.append(f"№{number}")
        if trip_date:
            chunks.append(trip_date)
        if plate:
            chunks.append(plate)
        if driver:
            chunks.append(driver)
        if len(chunks) == 1:
            chunks.append(str(sequence))
        return " · ".join(chunks)

    @staticmethod
    def _folder_path(
        *,
        trip_date: str,
        plate: str,
        vehicle: dict | None,
        driver_name: str,
        employee: dict | None,
    ) -> str:
        if trip_date:
            parsed = date.fromisoformat(trip_date)
            year = str(parsed.year)
            month = MONTHS_RU[parsed.month]
        else:
            year = "Без года"
            month = "Без месяца"
        registration = (
            vehicle.get("registration_number")
            if vehicle
            else plate
        ) or "Неизвестный автомобиль"
        vehicle_name = (
            " ".join(
                part
                for part in (
                    vehicle.get("make") if vehicle else "",
                    vehicle.get("model") if vehicle else "",
                )
                if part
            )
        )
        vehicle_folder = _safe(
            " ".join(part for part in (registration, vehicle_name) if part),
            "Неизвестный автомобиль",
        )
        driver = (
            employee.get("full_name")
            if employee
            else driver_name
        )
        driver_folder = _safe(_initials(driver), "Неизвестный водитель")
        return (
            Path("Путевые листы")
            / year
            / month
            / vehicle_folder
            / driver_folder
        ).as_posix()

    def _link_document_to_batch(self, waybill_id: str, batch_document_id: str) -> None:
        self.db.execute(
            """
            INSERT INTO work_document_relations(
                id, source_document_id, target_document_id,
                relation_type, score, evidence_json, created_at
            )
            VALUES(?, ?, ?, 'extracted_from', 1.0, ?, ?)
            ON CONFLICT(source_document_id, target_document_id, relation_type)
            DO UPDATE SET score=1.0, evidence_json=excluded.evidence_json
            """,
            (
                str(uuid4()),
                waybill_id,
                batch_document_id,
                _json({"source": "waybill_batch"}),
                _now(),
            ),
        )

    def _relation(
        self,
        source_type: str,
        source_id: str,
        relation_type: str,
        target_type: str,
        target_id: str,
        *,
        source_document_id: str | None,
        confidence: float,
        evidence: dict,
    ) -> None:
        now = _now()
        self.db.execute(
            """
            INSERT INTO work_entity_relations(
                id, source_type, source_id, relation_type,
                target_type, target_id, source_document_id,
                confidence, evidence_json, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_type, source_id, relation_type, target_type, target_id)
            DO UPDATE SET
                source_document_id=excluded.source_document_id,
                confidence=excluded.confidence,
                evidence_json=excluded.evidence_json,
                updated_at=excluded.updated_at
            """,
            (
                str(uuid4()),
                source_type,
                source_id,
                relation_type,
                target_type,
                target_id,
                source_document_id,
                float(confidence),
                _json(evidence),
                now,
                now,
            ),
        )

    def _write_memory_and_graph(self, waybill_id: str) -> None:
        waybill = self.waybill(waybill_id)
        source_document_id = waybill.get("source_document_id") or waybill_id
        if waybill.get("employee_id") and waybill.get("vehicle_id"):
            self._relation(
                "employee",
                waybill["employee_id"],
                "drove",
                "vehicle",
                waybill["vehicle_id"],
                source_document_id=source_document_id,
                confidence=float(waybill.get("confidence") or 0),
                evidence={"waybill_id": waybill_id, "date": waybill.get("trip_date")},
            )
        if waybill.get("vehicle_id"):
            self._relation(
                "vehicle",
                waybill["vehicle_id"],
                "has_waybill",
                "waybill",
                waybill_id,
                source_document_id=source_document_id,
                confidence=1.0,
                evidence={"date": waybill.get("trip_date")},
            )
        if waybill.get("trip_date"):
            self._relation(
                "waybill",
                waybill_id,
                "on_date",
                "date",
                waybill["trip_date"],
                source_document_id=source_document_id,
                confidence=1.0,
                evidence={},
            )
        if waybill.get("employee_id") and waybill.get("fuel_card_number"):
            self._relation(
                "employee",
                waybill["employee_id"],
                "uses_fuel_card",
                "fuel_card",
                waybill["fuel_card_number"],
                source_document_id=source_document_id,
                confidence=self._field_confidence(waybill_id, "fuel_card_number"),
                evidence={"waybill_id": waybill_id},
            )

        existing = self.db.query(
            "SELECT id FROM ai_memory_items WHERE source=? LIMIT 1",
            (f"waybill:{waybill_id}",),
        )
        if not existing and waybill.get("trip_date"):
            driver = waybill.get("full_name") or waybill.get("driver_name") or "Неизвестный водитель"
            vehicle = " ".join(
                part for part in (
                    waybill.get("garage_make") or waybill.get("vehicle_make"),
                    waybill.get("garage_model") or waybill.get("vehicle_model"),
                    waybill.get("registration_number"),
                )
                if part
            )
            content = (
                f"{waybill['trip_date']}: {driver} управлял {vehicle or 'неопределённым автомобилем'}. "
                f"Выезд {waybill.get('departure_time') or 'не определён'}, "
                f"возвращение {waybill.get('return_time') or 'не определено'}, "
                f"пробег {waybill.get('distance_km') or 0:g} км."
            )
            self.memory.remember(
                "project:work",
                content,
                source=f"waybill:{waybill_id}",
                metadata={
                    "source_document_id": source_document_id,
                    "waybill_id": waybill_id,
                    "batch_id": waybill.get("batch_id"),
                },
            )

    def _anomaly(
        self,
        waybill_id: str,
        anomaly_type: str,
        severity: str,
        message: str,
        details: dict,
    ) -> None:
        existing = self.db.query(
            """
            SELECT id
            FROM garage_waybill_anomalies
            WHERE waybill_id=? AND anomaly_type=? AND resolved=0
              AND details_json=?
            LIMIT 1
            """,
            (waybill_id, anomaly_type, _json(details)),
        )
        if existing:
            return
        now = _now()
        self.db.execute(
            """
            INSERT INTO garage_waybill_anomalies(
                id, waybill_id, anomaly_type, severity,
                message, details_json, resolved, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                str(uuid4()),
                waybill_id,
                anomaly_type,
                severity,
                message,
                _json(details),
                now,
                now,
            ),
        )

    def _audit(
        self,
        *,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        field_name: str = "",
        original_value: str | None = None,
        new_value: str | None = None,
        reason: str = "",
        source: str = "",
        source_document_id: str | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO work_audit_log(
                id, actor, action, entity_type, entity_id, field_name,
                original_value, new_value, reason, source,
                source_document_id, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                actor,
                action,
                entity_type,
                entity_id,
                field_name,
                original_value,
                new_value,
                reason,
                source,
                source_document_id,
                _now(),
            ),
        )

    def _field_confidence(self, waybill_id: str, key: str) -> float:
        rows = self.db.query(
            """
            SELECT confidence, verified
            FROM garage_waybill_fields
            WHERE waybill_id=? AND field_key=?
            """,
            (waybill_id, key),
        )
        if not rows:
            return 0.0
        if rows[0]["verified"]:
            return 1.0
        return float(rows[0]["confidence"] or 0)

    def _relink_after_correction(
        self,
        waybill_id: str,
        field_key: str,
        value: str,
    ) -> None:
        waybill = self.waybill(waybill_id)
        if field_key in {"vehicle_plate", "vehicle_vin"}:
            vehicle_id, confidence = self._resolve_vehicle(
                plate=value if field_key == "vehicle_plate" else (waybill.get("registration_number") or ""),
                vin=value if field_key == "vehicle_vin" else waybill.get("vehicle_vin", ""),
            )
            self.db.execute(
                "UPDATE garage_waybills SET vehicle_id=?, updated_at=? WHERE id=?",
                (vehicle_id, _now(), waybill_id),
            )
        if field_key in {"driver_name", "personnel_number", "fuel_card_number", "trip_date"}:
            current = self.waybill(waybill_id)
            employee_id, _ = self._resolve_employee(
                driver_name=value if field_key == "driver_name" else current.get("driver_name", ""),
                personnel_number=value if field_key == "personnel_number" else current.get("personnel_number", ""),
                fuel_card_number=value if field_key == "fuel_card_number" else current.get("fuel_card_number", ""),
                vehicle_id=current.get("vehicle_id"),
                trip_date=value if field_key == "trip_date" else current.get("trip_date", ""),
            )
            self.db.execute(
                "UPDATE garage_waybills SET employee_id=?, updated_at=? WHERE id=?",
                (employee_id, _now(), waybill_id),
            )

    def _recalculate_waybill(self, waybill_id: str) -> None:
        waybill = self.waybill(waybill_id)
        start = waybill.get("odometer_start")
        end = waybill.get("odometer_end")
        distance = self._distance(
            float(start) if start is not None else None,
            float(end) if end is not None else None,
        )
        actual = round(
            float(waybill.get("fuel_open_l") or 0)
            + float(waybill.get("fuel_issued_l") or 0)
            + float(waybill.get("refueled_l") or 0)
            - float(waybill.get("fuel_close_l") or 0),
            4,
        )
        norm = waybill.get("norm_l_per_100km")
        if norm is None and waybill.get("vehicle_id"):
            vehicle = self.garage.vehicle(waybill["vehicle_id"])
            norm = vehicle.get("default_norm_l_per_100km")
        norm_consumption = (
            round((distance or 0) * float(norm) / 100.0, 4)
            if norm is not None and distance is not None
            else None
        )
        deviation = (
            round(actual - norm_consumption, 4)
            if norm_consumption is not None
            else None
        )
        self.db.execute(
            """
            UPDATE garage_waybills
            SET distance_km=?, actual_consumption_l=?,
                norm_l_per_100km=?, norm_consumption_l=?,
                deviation_l=?, updated_at=?
            WHERE id=?
            """,
            (
                distance or 0.0,
                actual,
                norm,
                norm_consumption,
                deviation,
                _now(),
                waybill_id,
            ),
        )
        if actual < 0:
            self._anomaly(
                waybill_id,
                "negative_calculated_fuel_consumption",
                "error",
                "Расчётный фактический расход топлива отрицательный.",
                {"actual_consumption_l": actual},
            )
        if (
            norm_consumption is not None
            and norm_consumption > 0
            and actual > norm_consumption * 1.5
        ):
            self._anomaly(
                waybill_id,
                "fuel_consumption_above_norm",
                "warning",
                "Фактический расход существенно выше нормы.",
                {
                    "actual_l": actual,
                    "norm_l": norm_consumption,
                    "ratio": round(actual / norm_consumption, 3),
                },
            )

    @staticmethod
    def _actual_datetimes(waybill: dict):
        trip_date = waybill.get("trip_date")
        departure = _parse_clock(waybill.get("departure_time"))
        returned = _parse_clock(waybill.get("return_time"))
        if not trip_date or not departure or not returned:
            return None
        base = date.fromisoformat(trip_date)
        start = datetime.combine(base, datetime.min.time()).replace(
            hour=departure[0],
            minute=departure[1],
        )
        end = datetime.combine(base, datetime.min.time()).replace(
            hour=returned[0],
            minute=returned[1],
        )
        if end < start:
            end += timedelta(days=1)
        return start, end

    @staticmethod
    def _actual_interval_minutes(
        trip_date: str | None,
        departure: str | None,
        returned: str | None,
    ) -> int | None:
        interval = WaybillAutomationService._actual_datetimes({
            "trip_date": trip_date,
            "departure_time": departure,
            "return_time": returned,
        })
        if interval is None:
            return None
        return int((interval[1] - interval[0]).total_seconds() // 60)

    @staticmethod
    def _schedule_datetimes(
        trip_date: str,
        start_time: str,
        end_time: str,
    ):
        base = date.fromisoformat(trip_date)
        start_clock = _parse_clock(start_time)
        end_clock = _parse_clock(end_time)
        if not start_clock or not end_clock:
            raise ValueError("invalid employee schedule")
        start = datetime.combine(base, datetime.min.time()).replace(
            hour=start_clock[0],
            minute=start_clock[1],
        )
        end = datetime.combine(base, datetime.min.time()).replace(
            hour=end_clock[0],
            minute=end_clock[1],
        )
        if end <= start:
            end += timedelta(days=1)
        return start, end

    @staticmethod
    def _intervals_overlap(left: dict, right: dict) -> bool:
        left_interval = WaybillAutomationService._actual_datetimes(left)
        right_interval = WaybillAutomationService._actual_datetimes(right)
        if left_interval is None or right_interval is None:
            return False
        return max(left_interval[0], right_interval[0]) < min(
            left_interval[1],
            right_interval[1],
        )


class WaybillBatchWorker:
    def __init__(
        self,
        service: WaybillAutomationService,
        *,
        worker_id: str = "work-waybill-worker",
        poll_seconds: float = 1.0,
    ):
        self.service = service
        self.worker_id = worker_id
        self.poll_seconds = max(0.2, float(poll_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop,
            name="waybill-batch-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            task = self.service.workflow.claim(
                worker_id=self.worker_id,
                lease_seconds=300,
                kinds=["waybill.batch.process"],
                allowed_capabilities={"waybill_processing"},
            )
            if not task:
                self._stop.wait(self.poll_seconds)
                continue
            try:
                self.service.workflow.mark_running(task["id"], self.worker_id)
                result = self.service.process_batch(task["payload"]["batch_id"])
                self.service.workflow.complete(
                    task["id"],
                    self.worker_id,
                    result={
                        "batch_id": result["id"],
                        "status": result["status"],
                        "summary": self.service.batch_summary(result["id"]),
                    },
                )
            except Exception as exc:
                try:
                    self.service.workflow.fail(
                        task["id"],
                        self.worker_id,
                        f"{type(exc).__name__}: {exc}",
                        retry_delay_seconds=5,
                    )
                except Exception:
                    pass
            self._stop.wait(0.05)
