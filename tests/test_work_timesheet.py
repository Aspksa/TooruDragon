from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.system.database import Database
from core.work.timesheet import STATUS_CODES, TimesheetService


class TimesheetServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "timesheet.db")
        self.db.initialize("test")
        self.service = TimesheetService(self.db)
        self.employee = self.service.save_employee({
            "personnel_number": "0001",
            "full_name": "Иванов Иван Иванович",
            "department": "Транспорт",
            "position": "Водитель",
            "schedule_type": "5/2",
            "weekly_hours": 40,
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_employee_and_month_norm(self):
        summary = self.service.summary("2020-01")
        self.assertEqual(summary["totals"]["employees"], 1)
        self.assertEqual(summary["totals"]["planned_hours"], 184.0)
        self.assertEqual(summary["employees"][0]["planned_norm_hours"], 184.0)
        self.assertEqual(summary["employees"][0]["missing_days"], 23)

    def test_entry_upsert_and_status_code(self):
        first = self.service.save_entry({
            "employee_id": self.employee["id"],
            "work_date": "2020-01-06",
            "status": "work",
            "planned_hours": 8,
            "actual_hours": 8,
        })
        second = self.service.save_entry({
            "employee_id": self.employee["id"],
            "work_date": "2020-01-06",
            "status": "remote",
            "planned_hours": 8,
            "actual_hours": 7.5,
            "note": "Удалённая работа",
        })

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["status"], "remote")
        self.assertEqual(second["status_code"], STATUS_CODES["remote"])
        self.assertEqual(second["actual_hours"], 7.5)
        entries = self.service.entries("2020-01")
        self.assertEqual(len(entries), 1)

    def test_calendar_contains_missing_days_and_saved_entry(self):
        self.service.save_entry({
            "employee_id": self.employee["id"],
            "work_date": "2020-01-06",
            "status": "work",
            "actual_hours": 8,
        })
        data = self.service.calendar("2020-01")
        row = data["rows"][0]
        saved = next(cell for cell in row["days"] if cell["date"] == "2020-01-06")
        missing = next(cell for cell in row["days"] if cell["date"] == "2020-01-07")
        weekend = next(cell for cell in row["days"] if cell["date"] == "2020-01-04")

        self.assertEqual(saved["entry"]["status_code"], "Я")
        self.assertFalse(saved["missing"])
        self.assertTrue(missing["missing"])
        self.assertTrue(weekend["weekend"])
        self.assertFalse(weekend["missing"])

    def test_anomalies_detect_long_shift_overtime_and_weekend(self):
        self.service.save_entry({
            "employee_id": self.employee["id"],
            "work_date": "2020-01-04",
            "status": "work",
            "planned_hours": 0,
            "actual_hours": 13,
            "overtime_hours": 5,
        })
        anomalies = self.service.anomalies("2020-01")
        kinds = {item["type"] for item in anomalies}
        self.assertIn("long_shift", kinds)
        self.assertIn("high_overtime", kinds)
        self.assertIn("weekend_work", kinds)

    def test_nonworking_status_with_hours_is_flagged(self):
        self.service.save_entry({
            "employee_id": self.employee["id"],
            "work_date": "2020-01-08",
            "status": "sick",
            "planned_hours": 8,
            "actual_hours": 4,
        })
        anomalies = self.service.anomalies("2020-01")
        self.assertTrue(any(
            item["type"] == "hours_on_nonworking_status"
            for item in anomalies
        ))

    def test_night_hours_cannot_exceed_actual_hours(self):
        with self.assertRaises(ValueError):
            self.service.save_entry({
                "employee_id": self.employee["id"],
                "work_date": "2020-01-09",
                "status": "work",
                "actual_hours": 4,
                "night_hours": 5,
            })


if __name__ == "__main__":
    unittest.main()
