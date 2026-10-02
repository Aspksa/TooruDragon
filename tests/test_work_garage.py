from __future__ import annotations

import base64
import struct
import tempfile
import unittest
from pathlib import Path

from core.system.database import Database
from core.work.documents import DocumentIntelligenceService
from core.work.garage import GarageFuelService
from core.work.legacy_xls import LegacyXlsWorkbook
from core.work.timesheet import TimesheetService


FREE = 0xFFFFFFFF
END = 0xFFFFFFFE
FAT = 0xFFFFFFFD


def _record(record_id: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HH", record_id, len(payload)) + payload


def _bof(substream_type: int) -> bytes:
    return _record(
        0x0809,
        struct.pack("<HHHH", 0x0500, substream_type, 0x0DBB, 0x07CC),
    )


def _label(row: int, col: int, value: str) -> bytes:
    raw = value.encode("cp1251")
    return _record(
        0x0204,
        struct.pack("<HHHH", row, col, 0, len(raw)) + raw,
    )


def _number(row: int, col: int, value: float) -> bytes:
    return _record(
        0x0203,
        struct.pack("<HHH", row, col, 0) + struct.pack("<d", value),
    )


def _directory_entry(
    name: str,
    entry_type: int,
    *,
    start_sector: int,
    size: int,
    child: int = FREE,
) -> bytes:
    value = bytearray(128)
    encoded = (name + "\x00").encode("utf-16le")
    value[:len(encoded)] = encoded
    struct.pack_into("<H", value, 64, len(encoded))
    value[66] = entry_type
    value[67] = 1
    struct.pack_into("<I", value, 68, FREE)
    struct.pack_into("<I", value, 72, FREE)
    struct.pack_into("<I", value, 76, child)
    struct.pack_into("<I", value, 116, start_sector)
    struct.pack_into("<Q", value, 120, size)
    return bytes(value)


def build_fuel_statement_xls() -> bytes:
    sheet_name = "Выписка"
    codepage = _record(0x0042, struct.pack("<H", 1251))
    global_prefix = _bof(0x0005) + codepage

    # First build BOUNDSHEET with a temporary offset, then recompute it.
    name_raw = sheet_name.encode("cp1251")
    temp_boundsheet = _record(
        0x0085,
        struct.pack("<IH", 0, 0) + bytes([len(name_raw)]) + name_raw,
    )
    global_stream = global_prefix + temp_boundsheet + _record(0x000A)
    sheet_offset = len(global_stream)
    boundsheet = _record(
        0x0085,
        struct.pack("<IH", sheet_offset, 0)
        + bytes([len(name_raw)])
        + name_raw,
    )
    global_stream = global_prefix + boundsheet + _record(0x000A)
    sheet_offset = len(global_stream)

    # Rebuild once more with the final offset in case record size changed.
    boundsheet = _record(
        0x0085,
        struct.pack("<IH", sheet_offset, 0)
        + bytes([len(name_raw)])
        + name_raw,
    )
    global_stream = global_prefix + boundsheet + _record(0x000A)

    sheet = bytearray()
    sheet += _bof(0x0010)
    sheet += _label(0, 0, "Выписка по пластиковым картам Айти")
    sheet += _label(1, 0, "Период с 01.06.2026 по 30.06.2026")
    sheet += _label(3, 0, "Карта № 5019801000000000001       Авто: ")
    sheet += _label(3, 3, "ИВАНОВ")
    for col, value in enumerate(
        ["Операция", "Дата", "Время", "Азс", "Топливо", "Цена", "Кол-во", "Сумма"]
    ):
        sheet += _label(4, col, value)
    sheet += _label(5, 0, "Отгрузка")
    sheet += _label(5, 1, "05.06.2026")
    sheet += _label(5, 2, "10:15:00")
    sheet += _label(5, 3, "АЗС - 1")
    sheet += _label(5, 4, "Бензин АИ-95")
    sheet += _number(5, 5, 71.85)
    sheet += _number(5, 6, 10.0)
    sheet += _number(5, 7, 718.50)
    sheet += _record(0x000A)

    workbook = global_stream + bytes(sheet)
    if len(workbook) > 4608:
        raise AssertionError("synthetic workbook is unexpectedly large")
    workbook += b"\x00" * (4608 - len(workbook))

    sector_size = 512
    header = bytearray(512)
    header[:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<H", header, 24, 0x003E)
    struct.pack_into("<H", header, 26, 3)
    struct.pack_into("<H", header, 28, 0xFFFE)
    struct.pack_into("<H", header, 30, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into("<I", header, 40, 0)
    struct.pack_into("<I", header, 44, 1)
    struct.pack_into("<I", header, 48, 9)
    struct.pack_into("<I", header, 52, 0)
    struct.pack_into("<I", header, 56, 4096)
    struct.pack_into("<I", header, 60, END)
    struct.pack_into("<I", header, 64, 0)
    struct.pack_into("<I", header, 68, END)
    struct.pack_into("<I", header, 72, 0)
    for index in range(109):
        struct.pack_into("<I", header, 76 + index * 4, FREE)
    struct.pack_into("<I", header, 76, 10)

    directory = bytearray(sector_size)
    directory[0:128] = _directory_entry(
        "Root Entry",
        5,
        start_sector=END,
        size=0,
        child=1,
    )
    directory[128:256] = _directory_entry(
        "Book",
        2,
        start_sector=0,
        size=len(workbook),
    )

    fat = [FREE] * (sector_size // 4)
    for index in range(8):
        fat[index] = index + 1
    fat[8] = END
    fat[9] = END
    fat[10] = FAT
    fat_sector = struct.pack("<" + "I" * len(fat), *fat)

    return bytes(header) + workbook + bytes(directory) + fat_sector


class GarageFuelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "garage.db")
        self.db.initialize("test")
        self.timesheet = TimesheetService(self.db)
        self.documents = DocumentIntelligenceService(self.db)
        self.garage = GarageFuelService(self.db)
        self.employee = self.timesheet.save_employee({
            "personnel_number": "0001",
            "full_name": "Иванов Иван Иванович",
            "department": "Администрация",
            "position": "Водитель",
            "weekly_hours": 40,
        })
        self.vehicle = self.garage.save_vehicle({
            "registration_number": "А123ВС25",
            "vin": "JH4TB2H26CC000001",
            "make": "Toyota",
            "model": "Land Cruiser",
            "fuel_type": "gasoline_95",
            "default_norm_l_per_100km": 20,
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_xls_reader_extracts_statement_cells(self):
        workbook = LegacyXlsWorkbook(build_fuel_statement_xls())
        sheet = workbook.first_sheet()
        self.assertEqual(
            sheet.cells[(0, 0)],
            "Выписка по пластиковым картам Айти",
        )
        self.assertEqual(sheet.cells[(5, 1)], "05.06.2026")
        self.assertEqual(sheet.cells[(5, 6)], 10.0)
        self.assertEqual(sheet.cells[(5, 7)], 718.5)

    def test_card_driver_vehicle_statement_and_waybill_flow(self):
        self.garage.set_employee_fuel_card(
            self.employee["id"],
            "5019801000000000001",
            valid_from="2026-06-01",
        )
        self.garage.assign_driver_vehicle(
            self.employee["id"],
            self.vehicle["id"],
            valid_from="2026-06-01",
        )

        raw = build_fuel_statement_xls()
        document = self.documents.ingest_file({
            "filename": "fuel_statement_2026-06.xls",
            "content_base64": base64.b64encode(raw).decode("ascii"),
            "source": "test",
        })
        self.assertEqual(document["document_type"], "fuel_statement")
        self.assertEqual(document["archive_path"], "Выписки ГСМ/2026/06")
        self.assertEqual(document["document_date"], "2026-06-01")
        self.assertEqual(document["document_number"], "")

        statement = self.garage.import_fuel_statement(
            document_id=document["id"],
            original_name=document["original_name"],
            content_base64=base64.b64encode(raw).decode("ascii"),
        )
        self.assertEqual(statement["card_count"], 1)
        self.assertEqual(statement["transaction_count"], 1)
        self.assertEqual(statement["total_liters"], 10.0)
        self.assertEqual(statement["total_amount"], 718.5)
        self.assertEqual(statement["resolution"]["linked"], 1)

        waybill = self.garage.save_waybill({
            "waybill_number": "ПЛ-1",
            "trip_date": "2026-06-05",
            "employee_id": self.employee["id"],
            "vehicle_id": self.vehicle["id"],
            "odometer_start": 1000,
            "odometer_end": 1050,
            "fuel_open_l": 20,
            "fuel_issued_l": 10,
            "fuel_close_l": 18,
        })
        self.assertEqual(waybill["distance_km"], 50.0)
        self.assertEqual(waybill["actual_consumption_l"], 12.0)
        self.assertEqual(waybill["norm_consumption_l"], 10.0)
        self.assertEqual(waybill["deviation_l"], 2.0)

        summary = self.garage.monthly_summary("2026-06")
        self.assertEqual(summary["statement"]["liters"], 10.0)
        self.assertEqual(summary["waybills"]["distance_km"], 50.0)
        self.assertEqual(summary["waybills"]["consumption_l"], 12.0)
        self.assertEqual(len(summary["rows"]), 1)
        self.assertEqual(
            summary["rows"][0]["statement_vs_waybill_liters"],
            0.0,
        )

    def test_unassigned_card_resolves_after_mapping_is_added(self):
        raw = build_fuel_statement_xls()
        document = self.documents.ingest_file({
            "filename": "statement.xls",
            "content_base64": base64.b64encode(raw).decode("ascii"),
        })
        statement = self.garage.import_fuel_statement(
            document_id=document["id"],
            original_name=document["original_name"],
            content_base64=base64.b64encode(raw).decode("ascii"),
        )
        self.assertEqual(statement["resolution"]["card_unassigned"], 1)
        self.assertEqual(len(self.garage.unresolved_cards("2026-06")), 1)

        self.garage.set_employee_fuel_card(
            self.employee["id"],
            "5019801000000000001",
            valid_from="2026-06-01",
        )
        self.assertEqual(
            self.garage.statement(statement["id"])["resolution"].get(
                "driver_no_vehicle"
            ),
            1,
        )
        self.garage.assign_driver_vehicle(
            self.employee["id"],
            self.vehicle["id"],
            valid_from="2026-06-01",
        )
        resolved = self.garage.statement(statement["id"])
        self.assertEqual(resolved["resolution"]["linked"], 1)
        self.assertEqual(self.garage.unresolved_cards("2026-06"), [])

    def test_employee_directory_exposes_current_fuel_card(self):
        self.garage.set_employee_fuel_card(
            self.employee["id"],
            "5019801000000000001",
        )
        employee = self.timesheet.employee(self.employee["id"])
        self.assertEqual(
            employee["fuel_card_number"],
            "5019801000000000001",
        )


if __name__ == "__main__":
    unittest.main()
