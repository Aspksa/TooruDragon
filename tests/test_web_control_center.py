from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from web.server import (
    ROOT,
    _allowed,
    _build_machine_report,
    _report_filename,
)


class WebControlCenterProxyTests(unittest.TestCase):
    def test_main_read_routes_are_allowlisted(self):
        self.assertTrue(_allowed("GET", "main", "/api/cores"))
        self.assertTrue(_allowed("GET", "main", "/api/tasks?limit=100"))
        self.assertTrue(_allowed("GET", "main", "/observability"))
        self.assertTrue(_allowed("GET", "tooru_ai", "/runtime"))
        self.assertTrue(_allowed("GET", "tooru_ai", "/memory/search?q=gateway"))
        self.assertTrue(_allowed("GET", "tooru_ai", "/rag/search?q=gateway"))
        self.assertTrue(_allowed("GET", "tooru_ai", "/rag/documents"))
        self.assertTrue(_allowed("GET", "work", "/timesheet/summary?month=2026-10"))
        self.assertTrue(_allowed("GET", "work", "/timesheet/calendar?month=2026-10"))
        self.assertTrue(_allowed("GET", "work", "/timesheet/overtime?month=2026-10"))
        self.assertTrue(_allowed("GET", "work", "/timesheet/custom-columns"))
        self.assertTrue(_allowed("GET", "work", "/documents?limit=100"))
        self.assertTrue(_allowed("GET", "work", "/documents/get?id=abc"))
        self.assertTrue(_allowed("GET", "work", "/documents/search?q=invoice"))
        self.assertTrue(_allowed("GET", "work", "/documents/graph"))
        self.assertTrue(_allowed("GET", "work", "/documents/stats"))
        self.assertTrue(_allowed("GET", "work", "/documents/ingest-history?limit=100"))
        self.assertTrue(_allowed("GET", "main", "/api/task/transitions?task_id=abc"))

    def test_control_actions_are_explicitly_allowlisted(self):
        self.assertTrue(_allowed("POST", "supervisor", "/core/action"))
        self.assertTrue(_allowed("POST", "supervisor", "/safe-mode/enable"))
        self.assertTrue(_allowed("POST", "main", "/agents/tool/invoke"))
        self.assertTrue(_allowed("POST", "tooru_ai", "/chat"))
        self.assertTrue(_allowed("POST", "tooru_ai", "/inference"))
        self.assertTrue(_allowed("POST", "tooru_ai", "/memory/remember"))
        self.assertTrue(_allowed("POST", "tooru_ai", "/rag/ingest"))
        self.assertTrue(_allowed("POST", "work", "/timesheet/employee/save"))
        self.assertTrue(_allowed("POST", "work", "/timesheet/entry/save"))
        self.assertTrue(_allowed("POST", "work", "/timesheet/custom-column/save"))
        self.assertTrue(_allowed("POST", "work", "/documents/ingest"))
        self.assertTrue(_allowed("POST", "work", "/documents/file-ingest"))
        self.assertTrue(_allowed("POST", "work", "/documents/reanalyze"))
        self.assertTrue(_allowed("POST", "work", "/documents/archive"))

    def test_arbitrary_local_proxying_is_rejected(self):
        self.assertFalse(_allowed("GET", "main", "/system"))
        self.assertFalse(_allowed("POST", "main", "/registry/register"))
        self.assertFalse(_allowed("GET", "gateway", "/core/home/health"))
        self.assertFalse(_allowed("POST", "supervisor", "/unknown"))
        self.assertFalse(_allowed("POST", "tooru_ai", "/arbitrary"))
        self.assertFalse(_allowed("POST", "work", "/timesheet/summary"))
        self.assertFalse(_allowed("POST", "work", "/documents/get"))

    def test_wrong_method_is_rejected(self):
        self.assertFalse(_allowed("POST", "main", "/api/cores"))
        self.assertFalse(_allowed("GET", "supervisor", "/core/action"))

    def test_machine_report_collects_available_sources_and_errors(self):
        def fake_fetcher(upstream, path, timeout=5.0):
            if upstream == "gateway" and path == "/routes":
                raise TimeoutError("gateway test timeout")
            return {
                "upstream": upstream,
                "path": path,
                "timeout": timeout,
                "status": "ok",
            }

        report = _build_machine_report(fetcher=fake_fetcher)

        self.assertEqual(report["schema"], "toorudragon.machine_report")
        self.assertEqual(report["schema_version"], "1.0")
        self.assertGreater(report["collection"]["requested"], 10)
        self.assertEqual(report["collection"]["failed"], 1)
        self.assertTrue(report["notes"]["partial_report"])
        self.assertIn("system.main.health", report["snapshot"])
        self.assertIn("ai.reasoning", report["snapshot"])
        self.assertEqual(
            report["collection"]["errors"][0]["source"],
            "gateway.routes",
        )

    def test_machine_report_filename_is_stable_and_ascii(self):
        value = _report_filename(
            datetime(2026, 10, 2, 1, 2, 3, tzinfo=timezone.utc)
        )
        self.assertEqual(
            value,
            "toorudragon-machine-report-20261002-010203.json",
        )
        value.encode("ascii")

    def test_audit_page_has_direct_report_download_link(self):
        html = (Path(ROOT) / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="/report/system.json"', html)
        self.assertIn('id="download-machine-report"', html)
        self.assertIn("download", html)

    def test_documents_workspace_replaces_duplicate_rag_panel(self):
        html = (Path(ROOT) / "index.html").read_text(encoding="utf-8")
        script = (Path(ROOT) / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-page="documents"', html)
        self.assertIn('id="document-passport"', html)
        self.assertIn('id="document-dna"', html)
        self.assertNotIn('id="ai-rag-ingest"', html)
        self.assertNotIn("loadRAGDocuments()", script)
        self.assertIn('$("[data-ts-custom-id]")', script)

    def test_machine_report_includes_document_intelligence(self):
        calls = []

        def fake_fetcher(upstream, path, timeout=5.0):
            calls.append((upstream, path))
            return {"status": "ok"}

        report = _build_machine_report(fetcher=fake_fetcher)
        self.assertIn("work.documents_status", report["snapshot"])
        self.assertIn("work.documents_stats", report["snapshot"])
        self.assertIn("work.documents_recent", report["snapshot"])
        self.assertIn("work.documents_graph", report["snapshot"])
        self.assertIn("work.documents_ingest_history", report["snapshot"])


if __name__ == "__main__":
    unittest.main()
