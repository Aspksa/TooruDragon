from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from core.system.database import Database
from core.work.documents import DocumentIntelligenceService
from core.work.garage import GarageFuelService
from core.work.timesheet import TimesheetService
from core.work.waybill_ocr import OCRPage, StaticOCRService
from core.work.waybills import WaybillAutomationService


CARD_1 = "5019801000000000001"
CARD_2 = "5019801000000000002"


def waybill_text(
    number: int,
    work_date: date,
    *,
    plate: str = "C 859 EC 25",
    driver: str = "Иванов Иван Иванович",
    personnel: str = "0001",
    departure: str = "07:15",
    returned: str | None = "19:40",
    odo_start: float = 125000,
    odo_end: float = 125200,
    fuel_open: float = 20,
    fuel_issued: float = 0,
    refueled: float = 10,
    fuel_close: float = 10,
    card: str = CARD_1,
    make_model: str = "Hyundai Santa Fe",
    route: str = "Гараж - объект - гараж",
) -> str:
    lines = [
        f"ПУТЕВОЙ ЛИСТ № {number}",
        f"Дата: {work_date.strftime('%d.%m.%Y')}",
        "Организация: Администрация",
        "Подразделение: Транспортный отдел",
        f"Автомобиль: {make_model}",
        f"Гос номер: {plate}",
        "VIN: KMHSH81XDCU000001",
        f"Водитель: {driver}",
        f"Табельный номер: {personnel}",
        f"Время выезда: {departure}",
    ]
    if returned is not None:
        lines.append(f"Время возвращения: {returned}")
    lines.extend([
        f"Пробег начало: {odo_start}",
        f"Пробег конец: {odo_end}",
        f"Остаток топлива начало: {fuel_open}",
        f"Выдано топлива: {fuel_issued}",
        f"Заправлено: {refueled}",
        f"Остаток топлива конец: {fuel_close}",
        "Марка топлива: Бензин АИ-95",
        f"Маршрут: {route}",
        "Задание: Служебная поездка",
        f"Топливная карта № {card}",
        "Примечание: без замечаний",
    ])
    return "\n".join(lines)


def page(
    number: int,
    text: str,
    confidence: float = 0.99,
) -> OCRPage:
    return OCRPage(
        page_number=number,
        text=text,
        confidence=confidence,
        engine="test_ocr",
        blocks=[{
            "text": text.splitlines()[0] if text.splitlines() else "",
            "left": 0,
            "top": 0,
            "width": 100,
            "height": 20,
            "confidence": confidence,
        }],
    )


class CountingOCR(StaticOCRService):
    def __init__(self, pages):
        super().__init__(pages)
        self.calls = 0

    def extract_pages(self, filename: str, raw: bytes):
        self.calls += 1
        return super().extract_pages(filename, raw)


class TestWaybillAutomationService(WaybillAutomationService):
    def _export_waybill_pdf(
        self,
        *,
        batch,
        raw_batch,
        page_numbers,
        folder_path,
        trip_date,
        waybill_number,
        sequence,
    ):
        filename = f"{trip_date or 'Без_даты'}_ПЛ_{waybill_number or sequence}.pdf"
        relative = Path("documents") / Path(folder_path) / filename
        target = self.data_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(
                b"%PDF-1.4\n% synthetic child pages "
                + ",".join(map(str, page_numbers)).encode("ascii")
                + b"\n"
            )
        return relative.as_posix()


class WaybillAutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "tooru.db")
        self.db.initialize("test")
        self.documents = DocumentIntelligenceService(self.db)
        self.garage = GarageFuelService(self.db)
        self.timesheet = TimesheetService(self.db)

        self.employee1 = self.timesheet.save_employee({
            "personnel_number": "0001",
            "full_name": "Иванов Иван Иванович",
            "department": "Транспортный отдел",
            "position": "Водитель",
            "weekly_hours": 40,
        })
        self.employee2 = self.timesheet.save_employee({
            "personnel_number": "0002",
            "full_name": "Петров Пётр Петрович",
            "department": "Транспортный отдел",
            "position": "Водитель",
            "weekly_hours": 40,
        })
        self.vehicle1 = self.garage.save_vehicle({
            "registration_number": "С859ЕС25",
            "vin": "KMHSH81XDCU000001",
            "make": "Hyundai",
            "model": "Santa Fe",
            "fuel_type": "gasoline_95",
            "tank_capacity_l": 70,
            "default_norm_l_per_100km": 10,
        })
        self.vehicle2 = self.garage.save_vehicle({
            "registration_number": "А123ВС25",
            "vin": "JH4TB2H26CC000001",
            "make": "Toyota",
            "model": "Land Cruiser",
            "fuel_type": "gasoline_95",
            "tank_capacity_l": 90,
            "default_norm_l_per_100km": 14,
        })
        self.garage.set_employee_fuel_card(
            self.employee1["id"],
            CARD_1,
        )
        self.garage.set_employee_fuel_card(
            self.employee2["id"],
            CARD_2,
        )
        self.garage.assign_driver_vehicle(
            self.employee1["id"],
            self.vehicle1["id"],
        )
        self.garage.assign_driver_vehicle(
            self.employee2["id"],
            self.vehicle2["id"],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def service(self, pages):
        ocr = CountingOCR(pages)
        service = TestWaybillAutomationService(
            self.db,
            documents=self.documents,
            garage=self.garage,
            timesheet=self.timesheet,
            ocr=ocr,
        )
        return service, ocr

    def add_schedule(self, service, employee=None, *, start="08:00", end="17:00"):
        service.save_schedule({
            "employee_id": (employee or self.employee1)["id"],
            "start_time": start,
            "end_time": end,
            "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "source": "test",
        })

    def process(self, pages, raw=b"synthetic-pdf", filename="batch.pdf"):
        service, ocr = self.service(pages)
        batch = service.upload_bytes(
            filename=filename,
            raw=raw,
            uploaded_by="tester",
            source="test",
        )
        result = service.process_batch(batch["id"])
        return service, ocr, result

    def test_full_pdf_waybill_to_confirmed_timesheet(self):
        service, ocr = self.service([
            page(1, waybill_text(153, date(2026, 9, 5)))
        ])
        self.add_schedule(service)
        batch = service.upload_bytes(
            filename="Путевые_листы_Сентябрь_2026.pdf",
            raw=b"one-waybill-pdf",
            uploaded_by="tester",
        )
        processed = service.process_batch(batch["id"])
        self.assertEqual(processed["status"], "completed")
        self.assertEqual(ocr.calls, 1)

        items = service.waybills(batch_id=batch["id"])
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["id"], item["source_document_id"])
        self.assertEqual(item["employee_id"], self.employee1["id"])
        self.assertEqual(item["vehicle_id"], self.vehicle1["id"])
        self.assertEqual(item["distance_km"], 200)
        self.assertEqual(item["actual_consumption_l"], 20)
        self.assertEqual(item["norm_consumption_l"], 20)
        self.assertFalse(item["needs_review"])
        self.assertEqual(item["source_pages"], [1])
        self.assertIn("Путевые листы/2026/09 Сентябрь/", item["folder_path"])
        self.assertTrue(
            (self.db.path.parent / item["individual_pdf_path"]).is_file()
        )

        document = self.documents.document(item["id"], include_text=False)
        self.assertEqual(document["document_type"], "waybill")
        self.assertEqual(document["id"], item["id"])

        candidate = item["overtime_candidate"]
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["overtime_before_minutes"], 45)
        self.assertEqual(candidate["overtime_after_minutes"], 160)
        self.assertEqual(candidate["overtime_total_minutes"], 205)
        before = self.timesheet.entries("2026-09")
        self.assertEqual(before, [])

        applied = service.review_overtime(
            candidate["id"],
            action="approve",
            actor="tester",
        )
        self.assertEqual(applied["status"], "applied_to_timesheet")
        entries = self.timesheet.entries("2026-09")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source"], "waybill_confirmed")
        self.assertEqual(entries[0]["overtime_hours"], 3.42)

        memories = self.db.query(
            "SELECT source, metadata_json FROM ai_memory_items WHERE source=?",
            (f"waybill:{item['id']}",),
        )
        self.assertEqual(len(memories), 1)
        self.assertIn(item["id"], memories[0]["metadata_json"])
        relations = self.db.query(
            "SELECT relation_type FROM work_entity_relations WHERE source_document_id=?",
            (item["id"],),
        )
        self.assertTrue(relations)

    def test_pdf_with_fifty_waybills(self):
        start = date(2026, 9, 1)
        pages = []
        odometer = 200000
        for index in range(50):
            day = start + timedelta(days=index)
            pages.append(page(
                index + 1,
                waybill_text(
                    1000 + index,
                    day,
                    odo_start=odometer,
                    odo_end=odometer + 10,
                    departure="08:10",
                    returned="16:50",
                    fuel_open=20,
                    refueled=1,
                    fuel_close=20,
                ),
            ))
            odometer += 10
        service, _ocr, batch = self.process(
            pages,
            raw=b"fifty-waybills",
            filename="50-waybills.pdf",
        )
        items = service.waybills(batch_id=batch["id"])
        self.assertEqual(len(items), 50)
        self.assertEqual(batch["waybills_detected"], 50)
        self.assertEqual(batch["waybills_completed"], 50)
        months = {item["trip_date"][:7] for item in items}
        self.assertIn("2026-09", months)
        self.assertIn("2026-10", months)

    def test_front_and_reverse_are_one_waybill(self):
        front = page(
            1,
            waybill_text(201, date(2026, 9, 7), departure="08:05", returned="16:55"),
        )
        reverse = page(
            2,
            "ОБОРОТНАЯ СТОРОНА ПУТЕВОГО ЛИСТА\n"
            "Маршрут: дополнительный объект\n"
            "Примечание: продолжение",
        )
        service, _ocr, batch = self.process(
            [front, reverse],
            raw=b"front-reverse",
        )
        items = service.waybills(batch_id=batch["id"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source_pages"], [1, 2])
        split_issues = [
            a for a in items[0]["anomalies"]
            if a["anomaly_type"] == "split_low_confidence"
        ]
        self.assertEqual(split_issues, [])

    def test_blurry_scan_needs_review(self):
        service, _ocr, batch = self.process([
            page(
                1,
                waybill_text(202, date(2026, 9, 8)),
                confidence=0.52,
            )
        ], raw=b"blurry")
        item = service.waybills(batch_id=batch["id"])[0]
        self.assertTrue(item["needs_review"])
        self.assertTrue(any(
            a["anomaly_type"].startswith("low_confidence_")
            for a in item["anomalies"]
        ))

    def test_unknown_driver_and_vehicle_are_saved_not_dropped(self):
        text = waybill_text(
            203,
            date(2026, 9, 9),
            plate="К 999 ХХ 99",
            driver="Неизвестный Николай Николаевич",
            personnel="9999",
            card="9999999999999999999",
        )
        service, _ocr, batch = self.process([page(1, text)], raw=b"unknown")
        item = service.waybills(batch_id=batch["id"])[0]
        self.assertIsNone(item["employee_id"])
        self.assertIsNone(item["vehicle_id"])
        self.assertTrue(item["needs_review"])
        kinds = {a["anomaly_type"] for a in item["anomalies"]}
        self.assertIn("unknown_driver", kinds)
        self.assertIn("unknown_vehicle", kinds)
        with self.assertRaisesRegex(ValueError, "Нельзя подтвердить"):
            service.confirm_waybill(item["id"])

    def test_bad_mileage_and_negative_fuel_are_anomalies(self):
        text = waybill_text(
            204,
            date(2026, 9, 10),
            odo_start=130000,
            odo_end=129900,
            fuel_open=-5,
            refueled=0,
            fuel_close=10,
        )
        service, _ocr, batch = self.process([page(1, text)], raw=b"bad-values")
        item = service.waybills(batch_id=batch["id"])[0]
        kinds = {a["anomaly_type"] for a in item["anomalies"]}
        self.assertIn("odometer_reversed", kinds)
        self.assertIn("negative_fuel", kinds)
        self.assertIn("negative_calculated_fuel_consumption", kinds)

    def test_duplicate_upload_uses_sha256_and_does_not_duplicate(self):
        pages = [page(1, waybill_text(205, date(2026, 9, 11)))]
        service, _ocr = self.service(pages)
        first = service.upload_bytes(filename="same.pdf", raw=b"same")
        second = service.upload_bytes(filename="same-copy.pdf", raw=b"same")
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["duplicate"])
        batches = service.batches()
        self.assertEqual(len(batches), 1)

    def test_retry_reuses_ocr_and_canonical_waybill(self):
        pages = [page(1, waybill_text(206, date(2026, 9, 12)))]
        service, ocr = self.service(pages)
        batch = service.upload_bytes(filename="retry.pdf", raw=b"retry")
        service.process_batch(batch["id"])
        first = service.waybills(batch_id=batch["id"])
        self.assertEqual(len(first), 1)
        self.assertEqual(ocr.calls, 1)

        self.db.execute(
            "UPDATE work_waybill_batches SET status='failed', stage='ocr' WHERE id=?",
            (batch["id"],),
        )
        service.process_batch(batch["id"])
        second = service.waybills(batch_id=batch["id"])
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["id"], first[0]["id"])
        self.assertEqual(ocr.calls, 1)

    def test_vehicle_and_driver_changes_in_one_batch(self):
        texts = [
            waybill_text(207, date(2026, 9, 13)),
            waybill_text(
                208,
                date(2026, 9, 14),
                plate="А 123 ВС 25",
                driver="Петров П.П.",
                personnel="0002",
                card=CARD_2,
                make_model="Toyota Land Cruiser",
                odo_start=50000,
                odo_end=50100,
            ),
        ]
        service, _ocr, batch = self.process(
            [page(1, texts[0]), page(2, texts[1])],
            raw=b"driver-vehicle-change",
        )
        items = sorted(
            service.waybills(batch_id=batch["id"]),
            key=lambda x: x["trip_date"],
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["employee_id"], self.employee1["id"])
        self.assertEqual(items[0]["vehicle_id"], self.vehicle1["id"])
        self.assertEqual(items[1]["employee_id"], self.employee2["id"])
        self.assertEqual(items[1]["vehicle_id"], self.vehicle2["id"])

    def test_missing_return_time_requires_review_and_no_overtime(self):
        text = waybill_text(
            209,
            date(2026, 9, 15),
            returned=None,
        )
        service, _ocr, batch = self.process([page(1, text)], raw=b"missing-return")
        item = service.waybills(batch_id=batch["id"])[0]
        self.assertTrue(item["needs_review"])
        self.assertIsNone(item["overtime_candidate"])
        self.assertTrue(any(
            a["anomaly_type"] == "missing_return_time"
            for a in item["anomalies"]
        ))

    def test_overtime_before_after_both_none_and_night_transition(self):
        cases = [
            ("before", "07:15", "16:00", 45),
            ("after", "08:30", "19:40", 160),
            ("both", "07:15", "19:40", 205),
            ("none", "08:15", "16:30", 0),
            ("night", "22:00", "01:30", 210),
        ]
        for index, (name, departure, returned, minutes) in enumerate(cases):
            with self.subTest(name=name):
                raw = ("overtime-"+name).encode("ascii")
                service, _ocr = self.service([
                    page(
                        1,
                        waybill_text(
                            300 + index,
                            date(2026, 9, 16 + index),
                            departure=departure,
                            returned=returned,
                        ),
                    )
                ])
                self.add_schedule(service)
                batch = service.upload_bytes(
                    filename=f"{name}.pdf",
                    raw=raw,
                )
                service.process_batch(batch["id"])
                item = service.waybills(batch_id=batch["id"])[0]
                candidate = item["overtime_candidate"]
                self.assertEqual(candidate["overtime_total_minutes"], minutes)
                if name == "night":
                    self.assertFalse(any(
                        a["anomaly_type"] == "return_before_departure_ambiguous"
                        for a in item["anomalies"]
                    ))

    def test_different_months_machines_and_drivers_in_one_batch(self):
        pages = [
            page(1, waybill_text(401, date(2026, 9, 30))),
            page(2, waybill_text(
                402,
                date(2026, 10, 1),
                plate="А 123 ВС 25",
                driver="Петров Пётр Петрович",
                personnel="0002",
                card=CARD_2,
                make_model="Toyota Land Cruiser",
                odo_start=50000,
                odo_end=50120,
            )),
        ]
        service, _ocr, batch = self.process(
            pages,
            raw=b"two-months",
        )
        items = service.waybills(batch_id=batch["id"])
        folders = {item["trip_date"]: item["folder_path"] for item in items}
        self.assertIn("/09 Сентябрь/", folders["2026-09-30"])
        self.assertIn("/10 Октябрь/", folders["2026-10-01"])

    def test_monthly_mileage_uses_first_and_last_odometer_and_flags_gap(self):
        texts = [
            waybill_text(
                501, date(2026, 9, 1),
                odo_start=1000, odo_end=1100,
                departure="08:10", returned="16:30",
            ),
            waybill_text(
                502, date(2026, 9, 2),
                odo_start=1090, odo_end=1200,
                departure="08:10", returned="16:30",
            ),
        ]
        service, _ocr, batch = self.process(
            [page(1, texts[0]), page(2, texts[1])],
            raw=b"monthly-mileage",
        )
        summary = service.monthly_mileage_summary("2026-09")
        vehicle = summary["vehicles"][0]
        self.assertEqual(vehicle["monthly_mileage_km"], 200)
        self.assertEqual(len(vehicle["sequence_gaps"]), 1)
        second = sorted(
            service.waybills(batch_id=batch["id"]),
            key=lambda x: x["trip_date"],
        )[1]
        self.assertTrue(any(
            a["anomaly_type"] == "odometer_sequence_gap"
            for a in second["anomalies"]
        ))

    def test_fuel_statement_linkage_tank_capacity_and_graph(self):
        service, _ocr = self.service([
            page(
                1,
                waybill_text(
                    601,
                    date(2026, 9, 21),
                    refueled=80,
                    fuel_open=10,
                    fuel_close=70,
                ),
            )
        ])
        self.db.execute(
            """
            INSERT INTO garage_fuel_transactions(
                id, statement_id, document_id, source_row,
                card_number, holder_label, employee_id, vehicle_id,
                operation, operation_date, operation_time, station,
                fuel_name, fuel_kind, price_per_liter, quantity_l,
                amount, resolution_status, created_at, updated_at
            )
            VALUES(
                'tx-1', 'statement-1', 'statement-doc-1', 1,
                ?, 'ИВАНОВ', ?, ?, 'Отгрузка', '2026-09-21',
                '10:00', 'АЗС', 'АИ-95', 'gasoline_95', 70, 80,
                5600, 'linked', '2026-09-21T00:00:00+00:00',
                '2026-09-21T00:00:00+00:00'
            )
            """,
            (CARD_1, self.employee1["id"], self.vehicle1["id"]),
        )
        # Minimal parent rows required by foreign keys are not enforced by the
        # test connection by default, but the transaction still exercises the
        # real reconciliation queries.
        batch = service.upload_bytes(filename="fuel.pdf", raw=b"fuel")
        service.process_batch(batch["id"])
        item = service.waybills(batch_id=batch["id"])[0]
        kinds = {a["anomaly_type"] for a in item["anomalies"]}
        self.assertIn("refuel_exceeds_tank_capacity", kinds)
        graph = self.db.query(
            """
            SELECT relation_type, source_type, target_type
            FROM work_entity_relations
            WHERE target_id='tx-1' OR source_id='tx-1'
            """
        )
        relations = {row["relation_type"] for row in graph}
        self.assertIn("has_refuel", relations)
        self.assertIn("belongs_to_period", relations)

    def test_card_assigned_to_other_employee_is_detected(self):
        text = waybill_text(
            602,
            date(2026, 9, 22),
            driver="Иванов Иван Иванович",
            personnel="0001",
            card=CARD_2,
        )
        service, _ocr, batch = self.process([page(1, text)], raw=b"wrong-card")
        item = service.waybills(batch_id=batch["id"])[0]
        self.assertTrue(any(
            a["anomaly_type"] == "fuel_card_driver_mismatch"
            for a in item["anomalies"]
        ))

    def test_overlapping_two_drivers_one_vehicle_is_detected(self):
        # Second employee deliberately drives the first vehicle on the same
        # date/time; direct OCR name resolution remains deterministic.
        text1 = waybill_text(
            701,
            date(2026, 9, 23),
            departure="09:00",
            returned="12:00",
        )
        text2 = waybill_text(
            702,
            date(2026, 9, 23),
            driver="Петров Пётр Петрович",
            personnel="0002",
            card=CARD_2,
            departure="10:00",
            returned="13:00",
        )
        service, _ocr, batch = self.process(
            [page(1, text1), page(2, text2)],
            raw=b"vehicle-overlap",
        )
        items = service.waybills(batch_id=batch["id"])
        self.assertTrue(any(
            a["anomaly_type"] == "vehicle_two_drivers_same_time"
            for item in items
            for a in item["anomalies"]
        ))

    def test_ocr_correction_keeps_original_and_audit(self):
        text = waybill_text(801, date(2026, 9, 24))
        service, _ocr, batch = self.process([page(1, text)], raw=b"correction")
        item = service.waybills(batch_id=batch["id"])[0]
        corrected = service.correct_field(
            item["id"],
            field_key="return_time",
            corrected_value="18:40",
            actor="tester",
            reason="read from scan manually",
        )
        field = next(
            value for value in corrected["fields"]
            if value["field_key"] == "return_time"
        )
        self.assertEqual(field["original_value"], "19:40")
        self.assertEqual(field["corrected_value"], "18:40")
        self.assertTrue(field["verified"])
        audit = service.audit(entity_type="waybill", entity_id=item["id"])
        self.assertTrue(any(
            row["action"] == "waybill_field_corrected"
            for row in audit
        ))

    def test_overtime_correction_requires_second_confirmation(self):
        service, _ocr = self.service([
            page(1, waybill_text(901, date(2026, 9, 25)))
        ])
        self.add_schedule(service)
        batch = service.upload_bytes(filename="correct-ot.pdf", raw=b"correct-ot")
        service.process_batch(batch["id"])
        candidate = service.waybills(batch_id=batch["id"])[0]["overtime_candidate"]

        corrected = service.review_overtime(
            candidate["id"],
            action="correct",
            corrected_total_minutes=120,
            actor="tester",
        )
        self.assertEqual(corrected["status"], "needs_review")
        self.assertEqual(self.timesheet.entries("2026-09"), [])

        applied = service.review_overtime(
            candidate["id"],
            action="approve",
            actor="tester",
        )
        self.assertEqual(applied["status"], "applied_to_timesheet")
        self.assertEqual(
            self.timesheet.entries("2026-09")[0]["overtime_hours"],
            2.0,
        )


class WaybillMigrationTests(unittest.TestCase):
    def test_existing_waybill_table_is_rebuilt_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE system_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE work_employees(
                    id TEXT PRIMARY KEY,
                    personnel_number TEXT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    department TEXT NOT NULL DEFAULT '',
                    position TEXT NOT NULL DEFAULT '',
                    schedule_type TEXT NOT NULL DEFAULT '5/2',
                    weekly_hours REAL NOT NULL DEFAULT 40,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE garage_vehicles(
                    id TEXT PRIMARY KEY,
                    registration_number TEXT NOT NULL UNIQUE,
                    vin TEXT NOT NULL DEFAULT '',
                    make TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    department TEXT NOT NULL DEFAULT '',
                    fuel_type TEXT NOT NULL DEFAULT '',
                    default_norm_l_per_100km REAL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE work_documents(
                    id TEXT PRIMARY KEY,
                    family_id TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    previous_document_id TEXT,
                    title TEXT NOT NULL,
                    original_name TEXT NOT NULL DEFAULT '',
                    document_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    document_number TEXT NOT NULL DEFAULT '',
                    document_date TEXT,
                    year INTEGER,
                    archive_path TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    source_path TEXT NOT NULL DEFAULT '',
                    text_content TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    normalized_sha256 TEXT NOT NULL,
                    structure_sha256 TEXT NOT NULL,
                    passport_json TEXT NOT NULL DEFAULT '{}',
                    dna_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE garage_waybills(
                    id TEXT PRIMARY KEY,
                    waybill_number TEXT NOT NULL DEFAULT '',
                    trip_date TEXT NOT NULL,
                    employee_id TEXT NOT NULL,
                    vehicle_id TEXT NOT NULL,
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
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO garage_waybills(
                    id, waybill_number, trip_date, employee_id, vehicle_id,
                    distance_km, fuel_open_l, fuel_issued_l, fuel_close_l,
                    actual_consumption_l, note, created_at, updated_at
                )
                VALUES(
                    'legacy-waybill', '77', '2026-06-01', 'emp', 'car',
                    100, 10, 20, 5, 25, 'legacy',
                    '2026-06-01T00:00:00+00:00',
                    '2026-06-01T00:00:00+00:00'
                );
                """
            )
            connection.commit()
            connection.close()

            db = Database(path)
            db.initialize("test")
            columns = {
                row["name"]: row
                for row in db.query("PRAGMA table_info(garage_waybills)")
            }
            self.assertIn("batch_id", columns)
            self.assertIn("needs_review", columns)
            self.assertIn("refueled_l", columns)
            self.assertEqual(columns["employee_id"]["notnull"], 0)
            self.assertEqual(columns["vehicle_id"]["notnull"], 0)
            rows = db.query(
                "SELECT * FROM garage_waybills WHERE id='legacy-waybill'"
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["waybill_number"], "77")
            vehicle_columns = {
                row["name"] for row in db.query("PRAGMA table_info(garage_vehicles)")
            }
            self.assertIn("tank_capacity_l", vehicle_columns)


if __name__ == "__main__":
    unittest.main()
