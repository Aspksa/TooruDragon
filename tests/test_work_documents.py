from __future__ import annotations

import base64
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.system.database import Database
from core.system.rag import RAGIndex
from core.work.documents import DocumentIntelligenceService


class DocumentIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "documents.db")
        self.db.initialize("test")
        self.service = DocumentIntelligenceService(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_invoice_is_not_misclassified_as_contract_reference(self):
        doc = self.service.ingest({
            "title": "Счёт № 55",
            "text": (
                "СЧЁТ № 55 от 10.01.2020\n"
                "Оплата товара по договору № 12 от 01.01.2020.\n"
                "Итого 12 500 руб."
            ),
        })
        self.assertEqual(doc["document_type"], "invoice")
        self.assertEqual(doc["document_number"], "55")
        self.assertEqual(doc["document_date"], "2020-01-10")
        self.assertEqual(doc["year"], 2020)
        self.assertEqual(doc["archive_path"], "Счета/2020")
        self.assertEqual(doc["passport"]["type"], "invoice")
        self.assertTrue(doc["dna"]["content_sha256"])
        self.assertTrue(doc["facts"])

    def test_service_memo_has_year_archive(self):
        doc = self.service.ingest({
            "title": "Служебная записка",
            "original_name": "01-СЗ-ремонт-2021.docx",
            "text": (
                "СЛУЖЕБНАЯ ЗАПИСКА № 17 от 15.03.2021\n"
                "Прошу выполнить ремонт автомобиля А123ВС25."
            ),
        })
        self.assertEqual(doc["document_type"], "service_memo")
        self.assertEqual(doc["archive_path"], "Служебные записки/2021")
        self.assertEqual(doc["status"], "studied")

    def test_exact_duplicate_is_not_created_twice(self):
        payload = {
            "title": "Акт № 4",
            "text": "АКТ № 4 от 01.02.2020\nРаботы выполнены.",
        }
        first = self.service.ingest(payload)
        second = self.service.ingest(payload)

        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(self.service.stats()["documents"]["active"], 1)

    def test_same_contract_number_creates_version_family(self):
        first = self.service.ingest({
            "title": "Договор № 77",
            "text": "ДОГОВОР № 77 от 01.01.2020\nЦена 1000 руб.",
        })
        second = self.service.ingest({
            "title": "Договор № 77",
            "text": "ДОГОВОР № 77 от 02.01.2020\nЦена 1200 руб.",
        })

        self.assertEqual(first["family_id"], second["family_id"])
        self.assertEqual(first["version"], 1)
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["previous_document_id"], first["id"])
        kinds = {item["relation_type"] for item in second["relations"]}
        self.assertIn("supersedes", kinds)
        issue_types = {item["issue_type"] for item in second["issues"]}
        self.assertIn("version_core_fields_changed", issue_types)
        self.assertEqual(second["status"], "attention")

    def test_invoice_offer_services_rule_is_error(self):
        doc = self.service.ingest({
            "title": "Счёт-оферта № 9",
            "text": (
                "СЧЁТ-ОФЕРТА № 9 от 05.05.2020\n"
                "Услуги по ремонту автомобиля."
            ),
        })
        issue_types = {item["issue_type"] for item in doc["issues"]}
        self.assertIn("invoice_offer_contains_services", issue_types)
        self.assertEqual(doc["status"], "error")

    def test_service_memo_extracts_labeled_facts_and_request(self):
        doc = self.service.ingest({
            "title": "Служебная записка № 18",
            "text": (
                "СЛУЖЕБНАЯ ЗАПИСКА № 18 от 16.03.2021\n"
                "Кому: Директору\n"
                "От кого: Начальника отдела\n"
                "Подразделение: Транспортный отдел\n"
                "Тема: Ремонт автомобиля\n"
                "Прошу выполнить ремонт автомобиля А123ВС25.\n"
                "Количество: 2 шт. НДС 20%."
            ),
        })
        by_key = {item["fact_key"]: item for item in doc["facts"]}
        self.assertEqual(by_key["addressee"]["value_text"], "Директору")
        self.assertEqual(by_key["author"]["value_text"], "Начальника отдела")
        self.assertEqual(by_key["department"]["value_text"], "Транспортный отдел")
        self.assertEqual(by_key["subject"]["value_text"], "Ремонт автомобиля")
        self.assertIn("Прошу выполнить ремонт", by_key["requested_action"]["value_text"])
        self.assertIn("vat", by_key)
        self.assertIn("quantity", by_key)
        self.assertEqual(doc["dna"]["version"], "1.1")
        self.assertTrue(doc["dna"]["fact_fingerprint"])

    def test_referenced_contract_counterparty_conflict_is_error(self):
        contract = self.service.ingest({
            "title": "Договор № 12",
            "text": (
                "ДОГОВОР № 12 от 01.01.2020\n"
                "Контрагент: ООО Ромашка\n"
                "Предмет договора."
            ),
        })
        invoice = self.service.ingest({
            "title": "Счёт № 55",
            "text": (
                "СЧЁТ № 55 от 10.01.2020\n"
                "Поставщик: ООО Василёк\n"
                "По договору № 12 от 01.01.2020.\n"
                "Итого 1000 руб."
            ),
        })
        self.assertNotEqual(contract["id"], invoice["id"])
        issue_types = {item["issue_type"] for item in invoice["issues"]}
        self.assertIn("counterparty_conflict", issue_types)
        self.assertEqual(invoice["status"], "error")

    def test_filename_year_conflict_is_reported(self):
        doc = self.service.ingest({
            "title": "Приказ № 5",
            "original_name": "Приказ_2019.docx",
            "text": "ПРИКАЗ № 5 от 10.01.2020\nО назначении ответственного.",
        })
        issue_types = {item["issue_type"] for item in doc["issues"]}
        self.assertIn("filename_year_conflict", issue_types)
        self.assertEqual(doc["status"], "attention")

    def test_same_plate_with_different_vin_is_error(self):
        first = self.service.ingest({
            "title": "Документ машины 1",
            "document_type": "vehicle_document",
            "text": (
                "Госномер А123ВС25\n"
                "VIN JH4TB2H26CC000001"
            ),
        })
        second = self.service.ingest({
            "title": "Документ машины 2",
            "document_type": "vehicle_document",
            "text": (
                "Госномер А123ВС25\n"
                "VIN JH4TB2H26CC000002"
            ),
        })
        self.assertNotEqual(first["id"], second["id"])
        issue_types = {item["issue_type"] for item in second["issues"]}
        self.assertIn("vehicle_identity_conflict", issue_types)
        self.assertEqual(second["status"], "error")

    def test_archive_removes_document_from_rag_but_preserves_work_record(self):
        doc = self.service.ingest({
            "title": "Акт № 44",
            "text": "АКТ № 44 от 01.04.2020\nУникальныйтестовыймаркер.",
        })
        rag = RAGIndex(self.db)
        self.assertTrue(any(item["id"] == doc["id"] for item in rag.documents()))

        archived = self.service.archive(doc["id"])

        self.assertTrue(archived["archived"])
        self.assertEqual(archived["status"], "archived")
        self.assertFalse(any(item["id"] == doc["id"] for item in rag.documents()))

    def test_docx_file_ingest_uses_builtin_parser(self):
        stream = io.BytesIO()
        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>ДОГОВОР № 8 от 08.08.2020</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Текст договора</w:t></w:r></w:p></w:body></w:document>'
        )
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("word/document.xml", xml)

        doc = self.service.ingest_file({
            "filename": "contract.docx",
            "content_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
        })
        self.assertEqual(doc["document_type"], "contract")
        self.assertEqual(doc["metadata"]["file"]["parser"], "builtin_docx_xml")
        self.assertEqual(doc["document_number"], "8")
        self.assertTrue(doc["passport"]["original_preserved"])
        stored = self.db.path.parent / doc["source_path"]
        self.assertTrue(stored.is_file())
        self.assertEqual(stored.read_bytes(), stream.getvalue())

    def test_xlsx_inline_string_ingest_uses_builtin_parser(self):
        stream = io.BytesIO()
        sheet = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData><row r="1">'
            '<c r="A1" t="inlineStr"><is><t>ТАБЕЛЬ рабочего времени</t></is></c>'
            '<c r="B1" t="inlineStr"><is><t>2020</t></is></c>'
            '</row></sheetData></worksheet>'
        )
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("xl/worksheets/sheet1.xml", sheet)

        doc = self.service.ingest_file({
            "filename": "timesheet.xlsx",
            "content_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
        })
        self.assertEqual(doc["document_type"], "timesheet")
        self.assertEqual(doc["metadata"]["file"]["parser"], "builtin_xlsx_xml")

    def test_legacy_doc_has_explicit_error(self):
        encoded = base64.b64encode(b"legacy binary").decode("ascii")
        with self.assertRaisesRegex(ValueError, "legacy .DOC"):
            self.service.ingest_file({
                "filename": "old.DOC",
                "content_base64": encoded,
            })

    def test_legacy_rag_documents_are_migrated_and_old_rows_removed(self):
        rag = RAGIndex(self.db)
        legacy = rag.ingest(
            "СЧЁТ № 501 от 02.02.2020\nТовар 1 шт. 500 руб.",
            title="Старый RAG счёт",
            source="legacy_ui",
        )
        self.assertEqual(self.service.legacy_rag_count(), 1)

        result = self.service.migrate_legacy_rag()

        self.assertEqual(result["migrated"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(self.service.legacy_rag_count(), 0)
        docs = self.service.documents()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["document_type"], "invoice")
        self.assertFalse(any(
            item["id"] == legacy["id"]
            for item in rag.documents()
        ))
        self.assertTrue(any(
            item["id"] == docs[0]["id"]
            for item in rag.documents()
        ))

    def test_ingest_history_and_stats_keep_failure_reason(self):
        self.service.record_ingest_event(
            filename="old.DOC",
            source="web_file",
            status="failed",
            error_type="ValueError",
            message="legacy .DOC is not safely parsed yet",
        )
        history = self.service.ingest_history()
        stats = self.service.stats()

        self.assertEqual(history[0]["filename"], "old.DOC")
        self.assertEqual(history[0]["status"], "failed")
        self.assertIn("legacy .DOC", history[0]["message"])
        self.assertEqual(stats["ingest"]["by_status"]["failed"], 1)
        self.assertEqual(
            stats["ingest"]["recent_failures"][0]["error_type"],
            "ValueError",
        )


if __name__ == "__main__":
    unittest.main()
