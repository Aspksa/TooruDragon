from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree
from datetime import datetime, timezone
from uuid import uuid4

from core.system.database import Database
from core.system.rag import RAGIndex


DATE_RE = re.compile(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{2}-\d{2})\b")
NUMBER_RE = re.compile(
    r"(?:№|N|номер)\s*[:#]?\s*([A-ZА-ЯЁ0-9][A-ZА-ЯЁ0-9./_-]{0,40})",
    re.IGNORECASE,
)
MONEY_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[\s\u00a0]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
    r"\s*(руб(?:\.|лей|ля)?|₽|RUB)\b",
    re.IGNORECASE,
)
VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
PLATE_RE = re.compile(
    r"\b[АВЕКМНОРСТУХABEKMHOPCTYX]\s*\d{3}\s*"
    r"[АВЕКМНОРСТУХABEKMHOPCTYX]{2}\s*\d{2,3}\b",
    re.IGNORECASE,
)
REFERENCE_RE = re.compile(
    r"\b(договор|контракт|приказ|акт|сч[её]т(?:-оферта)?)"
    r"\s*(?:№|N|номер)?\s*([A-ZА-ЯЁ0-9][A-ZА-ЯЁ0-9./_-]{0,40})",
    re.IGNORECASE,
)
WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_]+", re.UNICODE)
QUANTITY_RE = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(шт\.?|ед\.?|компл\.?|л\.?|кг\.?|м\.?)(?!\w)",
    re.IGNORECASE,
)
VAT_RE = re.compile(
    r"\bНДС\b\s*(?:(\d{1,2}(?:[.,]\d+)?)\s*%)?",
    re.IGNORECASE,
)
LABEL_PATTERNS = {
    "organization": re.compile(r"(?im)^\s*(?:организация|общество|компания)\s*[:\-]\s*(.+?)\s*$"),
    "department": re.compile(r"(?im)^\s*(?:подразделение|отдел|служба)\s*[:\-]\s*(.+?)\s*$"),
    "author": re.compile(r"(?im)^\s*(?:от кого|автор)\s*[:\-]\s*(.+?)\s*$"),
    "addressee": re.compile(r"(?im)^\s*(?:кому|адресат)\s*[:\-]\s*(.+?)\s*$"),
    "subject": re.compile(r"(?im)^\s*(?:тема|о чем|о чём)\s*[:\-]\s*(.+?)\s*$"),
    "supplier": re.compile(r"(?im)^\s*(?:поставщик|продавец)\s*[:\-]\s*(.+?)\s*$"),
    "counterparty": re.compile(r"(?im)^\s*(?:контрагент|заказчик|исполнитель)\s*[:\-]\s*(.+?)\s*$"),
}


DOCUMENT_TYPES = {
    "service_memo": "Служебная записка",
    "contract": "Договор",
    "invoice_offer": "Счёт-оферта",
    "invoice": "Счёт",
    "act": "Акт",
    "order": "Приказ",
    "timesheet": "Табель",
    "vehicle_document": "Документ на технику",
    "other": "Прочее",
}

TYPE_ARCHIVES = {
    "service_memo": "Служебные записки",
    "contract": "Договоры",
    "invoice_offer": "Счета-оферты",
    "invoice": "Счета",
    "act": "Акты",
    "order": "Приказы",
    "timesheet": "Табель",
    "vehicle_document": "Документы техники",
    "other": "Документы",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return "\n".join(
        " ".join(line.split())
        for line in str(text or "").replace("\r\n", "\n").split("\n")
        if line.strip()
    ).strip()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalized_value(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _parse_date(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parts = re.split(r"[./-]", raw)
    try:
        if len(parts) != 3:
            return None
        if len(parts[0]) == 4:
            year, month, day = map(int, parts)
        else:
            day, month, year = map(int, parts)
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


class DocumentIntelligenceService:
    """Canonical work-document store with passport, DNA, facts and RAG indexing."""

    def __init__(self, database: Database, rag: RAGIndex | None = None):
        self.db = database
        self.rag = rag or RAGIndex(database)

    def ingest_file(self, payload: dict) -> dict:
        filename = str(payload.get("filename") or "").strip()
        encoded = str(payload.get("content_base64") or "").strip()
        if not filename:
            raise ValueError("filename is required")
        if not encoded:
            raise ValueError("content_base64 is required")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError("invalid base64 file content") from exc

        if len(raw) > 12_000_000:
            raise ValueError("file is larger than 12 MB")

        text, parser = self._extract_file_text(filename, raw)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        metadata = {
            **metadata,
            "file": {
                "filename": filename,
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "parser": parser,
            },
        }
        item = self.ingest({
            "text": text,
            "title": payload.get("title") or Path(filename).stem,
            "original_name": filename,
            "source": payload.get("source") or "file_upload",
            "source_path": payload.get("source_path") or "",
            "document_type": payload.get("document_type") or "",
            "family_id": payload.get("family_id") or "",
            "metadata": metadata,
        })
        if item.get("duplicate"):
            return item

        try:
            stored_path = self._preserve_original(item, filename, raw)
            metadata["file"]["stored_path"] = stored_path
            passport = dict(item.get("passport") or {})
            passport["original_preserved"] = True
            passport["original_storage"] = stored_path
            self.db.execute(
                """
                UPDATE work_documents
                SET source_path=?, metadata_json=?, passport_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    stored_path,
                    json.dumps(metadata, ensure_ascii=False),
                    json.dumps(passport, ensure_ascii=False),
                    _now(),
                    item["id"],
                ),
            )
        except OSError as exc:
            self._add_issue(
                item["id"],
                "original_file_preservation_failed",
                "error",
                "Оригинал файла не удалось сохранить на диске проекта.",
                {"error_type": type(exc).__name__, "message": str(exc)},
            )
            self._sync_status(item["id"])

        return self.document(item["id"])

    def ingest(self, payload: dict) -> dict:
        text = _normalize_text(payload.get("text", ""))
        if not text:
            raise ValueError("document text is required")

        title = str(payload.get("title") or payload.get("original_name") or "Документ").strip()
        original_name = str(payload.get("original_name") or "").strip()
        source = str(payload.get("source") or "manual").strip()
        source_path = str(payload.get("source_path") or "").strip()
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

        content_hash = _sha256(text)
        duplicate = self.db.query(
            """
            SELECT id FROM work_documents
            WHERE content_sha256=? AND archived=0
            LIMIT 1
            """,
            (content_hash,),
        )
        if duplicate:
            item = self.document(duplicate[0]["id"])
            item["duplicate"] = True
            return item

        document_type = self._classify(
            title,
            text,
            forced_type=str(payload.get("document_type") or "").strip(),
        )
        facts = self._extract_facts(text)
        document_number = self._first_fact(facts, "document_number")
        document_date = self._first_fact(facts, "date")
        year = int(document_date[:4]) if document_date else self._infer_year(facts, text)

        family_id, previous_id, version = self._resolve_family(
            document_type=document_type,
            document_number=document_number,
            title=title,
            explicit_family_id=str(payload.get("family_id") or "").strip(),
        )

        archive_path = self._archive_path(document_type, year)
        normalized_hash = _sha256(re.sub(r"\s+", "", text).lower())
        structure = self._structure_signature(document_type, text, facts)
        structure_hash = _sha256(json.dumps(structure, ensure_ascii=False, sort_keys=True))
        document_id = str(uuid4())
        now = _now()

        passport = self._passport(
            document_id=document_id,
            family_id=family_id,
            version=version,
            title=title,
            original_name=original_name,
            document_type=document_type,
            document_number=document_number,
            document_date=document_date,
            year=year,
            archive_path=archive_path,
            facts=facts,
            content_hash=content_hash,
        )
        dna = self._dna(
            text=text,
            document_type=document_type,
            content_hash=content_hash,
            normalized_hash=normalized_hash,
            structure_hash=structure_hash,
            structure=structure,
            facts=facts,
        )

        with self.db.connect() as db:
            db.execute(
                """
                INSERT INTO work_documents(
                    id, family_id, version, previous_document_id, title,
                    original_name, document_type, status, document_number,
                    document_date, year, archive_path, source, source_path,
                    text_content, content_sha256, normalized_sha256,
                    structure_sha256, passport_json, dna_json, metadata_json,
                    archived, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, 'studied', ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    document_id,
                    family_id,
                    version,
                    previous_id,
                    title,
                    original_name,
                    document_type,
                    document_number or "",
                    document_date,
                    year,
                    archive_path,
                    source,
                    source_path,
                    text,
                    content_hash,
                    normalized_hash,
                    structure_hash,
                    json.dumps(passport, ensure_ascii=False),
                    json.dumps(dna, ensure_ascii=False),
                    json.dumps(metadata, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            for fact in facts:
                db.execute(
                    """
                    INSERT INTO work_document_facts(
                        id, document_id, fact_type, fact_key, value_text,
                        normalized_value, confidence, provenance_json,
                        verified, created_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        str(uuid4()),
                        document_id,
                        fact["type"],
                        fact["key"],
                        fact["value"],
                        fact["normalized"],
                        fact["confidence"],
                        json.dumps(fact["provenance"], ensure_ascii=False),
                        now,
                    ),
                )

        self._rebuild_issues(document_id)
        self._build_relations(document_id)
        self._cross_document_checks(document_id)

        if previous_id:
            self._upsert_relation(
                document_id,
                previous_id,
                "supersedes",
                1.0,
                {"family_id": family_id, "version": version},
            )
            self._compare_versions(document_id, previous_id)

        self._sync_status(document_id)

        self.rag.ingest(
            text,
            title=title,
            source="work_documents",
            document_id=document_id,
            metadata={
                "document_type": document_type,
                "family_id": family_id,
                "version": version,
                "archive_path": archive_path,
                "passport": passport,
                "dna": {
                    "content_sha256": dna["content_sha256"],
                    "structure_sha256": dna["structure_sha256"],
                },
            },
        )

        return self.document(document_id)

    def reanalyze(self, document_id: str) -> dict:
        current = self.document(document_id)
        text = current["text_content"]
        document_type = self._classify(current["title"], text)
        facts = self._extract_facts(text)
        document_number = self._first_fact(facts, "document_number")
        document_date = self._first_fact(facts, "date")
        year = int(document_date[:4]) if document_date else self._infer_year(facts, text)
        archive_path = self._archive_path(document_type, year)
        structure = self._structure_signature(document_type, text, facts)
        structure_hash = _sha256(json.dumps(structure, ensure_ascii=False, sort_keys=True))
        passport = self._passport(
            document_id=document_id,
            family_id=current["family_id"],
            version=current["version"],
            title=current["title"],
            original_name=current["original_name"],
            document_type=document_type,
            document_number=document_number,
            document_date=document_date,
            year=year,
            archive_path=archive_path,
            facts=facts,
            content_hash=current["content_sha256"],
        )
        dna = self._dna(
            text=text,
            document_type=document_type,
            content_hash=current["content_sha256"],
            normalized_hash=current["normalized_sha256"],
            structure_hash=structure_hash,
            structure=structure,
            facts=facts,
        )
        now = _now()
        with self.db.connect() as db:
            db.execute("DELETE FROM work_document_facts WHERE document_id=?", (document_id,))
            db.execute("DELETE FROM work_document_issues WHERE document_id=?", (document_id,))
            db.execute(
                """
                DELETE FROM work_document_relations
                WHERE source_document_id=? AND relation_type!='supersedes'
                """,
                (document_id,),
            )
            db.execute(
                """
                UPDATE work_documents
                SET document_type=?, status='studied', document_number=?,
                    document_date=?, year=?, archive_path=?, structure_sha256=?,
                    passport_json=?, dna_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    document_type,
                    document_number or "",
                    document_date,
                    year,
                    archive_path,
                    structure_hash,
                    json.dumps(passport, ensure_ascii=False),
                    json.dumps(dna, ensure_ascii=False),
                    now,
                    document_id,
                ),
            )
            for fact in facts:
                db.execute(
                    """
                    INSERT INTO work_document_facts(
                        id, document_id, fact_type, fact_key, value_text,
                        normalized_value, confidence, provenance_json,
                        verified, created_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        str(uuid4()),
                        document_id,
                        fact["type"],
                        fact["key"],
                        fact["value"],
                        fact["normalized"],
                        fact["confidence"],
                        json.dumps(fact["provenance"], ensure_ascii=False),
                        now,
                    ),
                )

        self._rebuild_issues(document_id)
        self._build_relations(document_id)
        self._cross_document_checks(document_id)
        self._sync_status(document_id)
        self.rag.ingest(
            text,
            title=current["title"],
            source="work_documents",
            document_id=document_id,
            metadata={
                "document_type": document_type,
                "family_id": current["family_id"],
                "version": current["version"],
                "archive_path": archive_path,
                "passport": passport,
                "dna": {
                    "content_sha256": dna["content_sha256"],
                    "structure_sha256": dna["structure_sha256"],
                },
            },
        )
        return self.document(document_id)

    def document(self, document_id: str, *, include_text: bool = True) -> dict:
        rows = self.db.query(
            """
            SELECT id, family_id, version, previous_document_id, title,
                   original_name, document_type, status, document_number,
                   document_date, year, archive_path, source, source_path,
                   text_content, content_sha256, normalized_sha256,
                   structure_sha256, passport_json, dna_json, metadata_json,
                   archived, created_at, updated_at
            FROM work_documents
            WHERE id=?
            """,
            (document_id,),
        )
        if not rows:
            raise KeyError(document_id)
        item = self._decode_document(dict(rows[0]))
        if not include_text:
            item.pop("text_content", None)
        item["facts"] = self.facts(document_id)
        item["issues"] = self.issues(document_id)
        item["relations"] = self.relations(document_id)
        return item

    def documents(
        self,
        *,
        limit: int = 100,
        document_type: str | None = None,
        status: str | None = None,
        year: int | None = None,
        include_archived: bool = False,
    ) -> list[dict]:
        clauses = []
        params: list = []
        if not include_archived:
            clauses.append("d.archived=0")
        if document_type:
            clauses.append("d.document_type=?")
            params.append(document_type)
        if status:
            clauses.append("d.status=?")
            params.append(status)
        if year:
            clauses.append("d.year=?")
            params.append(int(year))

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        rows = self.db.query(
            f"""
            SELECT d.id, d.family_id, d.version, d.previous_document_id,
                   d.title, d.original_name, d.document_type, d.status,
                   d.document_number, d.document_date, d.year, d.archive_path,
                   d.source, d.source_path, d.content_sha256,
                   d.normalized_sha256, d.structure_sha256,
                   d.passport_json, d.dna_json, d.metadata_json, d.archived,
                   d.created_at, d.updated_at,
                   COUNT(DISTINCT f.id) AS fact_count,
                   COUNT(DISTINCT CASE WHEN i.resolved=0 THEN i.id END) AS issue_count
            FROM work_documents d
            LEFT JOIN work_document_facts f ON f.document_id=d.id
            LEFT JOIN work_document_issues i ON i.document_id=d.id
            {where}
            GROUP BY d.id
            ORDER BY d.updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [self._decode_document(dict(row)) for row in rows]

    def search(self, query: str, *, limit: int = 50) -> list[dict]:
        query = str(query or "").strip()
        if not query:
            return []
        like = f"%{query}%"
        capped = max(1, min(int(limit), 200))
        rows = self.db.query(
            """
            SELECT DISTINCT d.id
            FROM work_documents d
            LEFT JOIN work_document_facts f ON f.document_id=d.id
            WHERE d.archived=0
              AND (
                d.title LIKE ? OR d.original_name LIKE ? OR
                d.document_number LIKE ? OR d.text_content LIKE ? OR
                f.value_text LIKE ?
              )
            ORDER BY d.updated_at DESC
            LIMIT ?
            """,
            (like, like, like, like, like, capped),
        )
        ids = [row["id"] for row in rows]
        seen = set(ids)
        if len(ids) < capped:
            for chunk in self.rag.search(query, limit=min(capped * 2, 100)):
                document_id = chunk["document_id"]
                if document_id in seen:
                    continue
                active = self.db.query(
                    "SELECT id FROM work_documents WHERE id=? AND archived=0",
                    (document_id,),
                )
                if not active:
                    continue
                ids.append(document_id)
                seen.add(document_id)
                if len(ids) >= capped:
                    break
        return [self.document(document_id, include_text=False) for document_id in ids]

    def archive(self, document_id: str) -> dict:
        self.document(document_id, include_text=False)
        with self.db.connect() as db:
            db.execute(
                """
                UPDATE work_documents
                SET archived=1, status='archived', updated_at=?
                WHERE id=?
                """,
                (_now(), document_id),
            )
            db.execute(
                "DELETE FROM ai_document_chunks WHERE document_id=?",
                (document_id,),
            )
            db.execute(
                "DELETE FROM ai_documents WHERE id=?",
                (document_id,),
            )
        return self.document(document_id, include_text=False)

    def facts(self, document_id: str) -> list[dict]:
        rows = self.db.query(
            """
            SELECT id, fact_type, fact_key, value_text, normalized_value,
                   confidence, provenance_json, verified, created_at
            FROM work_document_facts
            WHERE document_id=?
            ORDER BY fact_type, fact_key, id
            """,
            (document_id,),
        )
        for row in rows:
            row["provenance"] = json.loads(row.pop("provenance_json") or "{}")
            row["verified"] = bool(row["verified"])
        return rows

    def issues(self, document_id: str) -> list[dict]:
        rows = self.db.query(
            """
            SELECT id, issue_type, severity, message, details_json,
                   resolved, created_at
            FROM work_document_issues
            WHERE document_id=?
            ORDER BY resolved ASC,
                     CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                     created_at DESC
            """,
            (document_id,),
        )
        for row in rows:
            row["details"] = json.loads(row.pop("details_json") or "{}")
            row["resolved"] = bool(row["resolved"])
        return rows

    def relations(self, document_id: str) -> list[dict]:
        rows = self.db.query(
            """
            SELECT r.id, r.source_document_id, r.target_document_id,
                   r.relation_type, r.score, r.evidence_json, r.created_at,
                   d.title AS target_title, d.document_type AS target_type,
                   d.document_number AS target_number
            FROM work_document_relations r
            JOIN work_documents d ON d.id=r.target_document_id
            WHERE r.source_document_id=?
            ORDER BY r.score DESC, r.created_at DESC
            """,
            (document_id,),
        )
        for row in rows:
            row["evidence"] = json.loads(row.pop("evidence_json") or "{}")
        return rows

    def graph(self, *, limit: int = 200) -> dict:
        docs = self.documents(limit=limit)
        ids = {item["id"] for item in docs}
        if not ids:
            return {"nodes": [], "edges": []}
        placeholders = ",".join("?" for _ in ids)
        rows = self.db.query(
            f"""
            SELECT id, source_document_id, target_document_id,
                   relation_type, score, evidence_json
            FROM work_document_relations
            WHERE source_document_id IN ({placeholders})
              AND target_document_id IN ({placeholders})
            ORDER BY score DESC
            """,
            tuple(ids) + tuple(ids),
        )
        edges = []
        for row in rows:
            row["evidence"] = json.loads(row.pop("evidence_json") or "{}")
            edges.append(row)
        return {
            "nodes": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "document_type": item["document_type"],
                    "document_number": item["document_number"],
                    "version": item["version"],
                    "status": item["status"],
                    "issue_count": item.get("issue_count", 0),
                }
                for item in docs
            ],
            "edges": edges,
        }

    def record_ingest_event(
        self,
        *,
        filename: str = "",
        source: str = "manual",
        status: str,
        document_id: str | None = None,
        error_type: str = "",
        message: str = "",
    ) -> dict:
        event_id = str(uuid4())
        created_at = _now()
        self.db.execute(
            """
            INSERT INTO work_document_ingest_log(
                id, filename, source, status, document_id,
                error_type, message, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                str(filename or ""),
                str(source or "manual"),
                str(status),
                document_id,
                str(error_type or ""),
                str(message or ""),
                created_at,
            ),
        )
        return {
            "id": event_id,
            "filename": str(filename or ""),
            "source": str(source or "manual"),
            "status": str(status),
            "document_id": document_id,
            "error_type": str(error_type or ""),
            "message": str(message or ""),
            "created_at": created_at,
        }

    def ingest_history(self, limit: int = 100) -> list[dict]:
        return self.db.query(
            """
            SELECT id, filename, source, status, document_id,
                   error_type, message, created_at
            FROM work_document_ingest_log
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        )

    def legacy_rag_count(self) -> int:
        rows = self.db.query(
            """
            SELECT COUNT(*) AS count
            FROM ai_documents a
            LEFT JOIN work_documents w ON w.id=a.id
            WHERE w.id IS NULL
            """
        )
        return int(rows[0]["count"] or 0)

    def migrate_legacy_rag(self, *, limit: int = 500) -> dict:
        rows = self.db.query(
            """
            SELECT a.id, a.title, a.source, a.metadata_json
            FROM ai_documents a
            LEFT JOIN work_documents w ON w.id=a.id
            WHERE w.id IS NULL
            ORDER BY a.created_at ASC
            LIMIT ?
            """,
            (max(1, min(int(limit), 2000)),),
        )
        result = {
            "requested": len(rows),
            "migrated": 0,
            "duplicates": 0,
            "failed": 0,
            "items": [],
        }
        for legacy in rows:
            chunks = self.db.query(
                """
                SELECT content
                FROM ai_document_chunks
                WHERE document_id=?
                ORDER BY chunk_index ASC
                """,
                (legacy["id"],),
            )
            text = "\n".join(
                str(chunk["content"] or "").strip()
                for chunk in chunks
                if str(chunk["content"] or "").strip()
            ).strip()
            if not text:
                message = "legacy RAG document has no chunks"
                self.record_ingest_event(
                    filename=str(legacy["title"] or legacy["id"]),
                    source="legacy_rag",
                    status="failed",
                    error_type="LegacyRAGError",
                    message=message,
                )
                result["failed"] += 1
                result["items"].append({
                    "legacy_id": legacy["id"],
                    "status": "failed",
                    "message": message,
                })
                continue

            try:
                legacy_meta = json.loads(legacy["metadata_json"] or "{}")
                item = self.ingest({
                    "title": legacy["title"] or "Legacy RAG document",
                    "text": text,
                    "source": "legacy_rag",
                    "metadata": {
                        "legacy_rag": {
                            "id": legacy["id"],
                            "source": legacy["source"],
                            "metadata": legacy_meta,
                        },
                    },
                })
            except Exception as exc:
                self.record_ingest_event(
                    filename=str(legacy["title"] or legacy["id"]),
                    source="legacy_rag",
                    status="failed",
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
                result["failed"] += 1
                result["items"].append({
                    "legacy_id": legacy["id"],
                    "status": "failed",
                    "message": str(exc),
                })
                continue

            with self.db.connect() as db:
                db.execute(
                    "DELETE FROM ai_document_chunks WHERE document_id=?",
                    (legacy["id"],),
                )
                db.execute(
                    "DELETE FROM ai_documents WHERE id=?",
                    (legacy["id"],),
                )

            status = "duplicate" if item.get("duplicate") else "migrated"
            self.record_ingest_event(
                filename=str(legacy["title"] or legacy["id"]),
                source="legacy_rag",
                status=status,
                document_id=item["id"],
            )
            result["duplicates" if status == "duplicate" else "migrated"] += 1
            result["items"].append({
                "legacy_id": legacy["id"],
                "document_id": item["id"],
                "status": status,
            })
        return result

    def stats(self) -> dict:
        totals = self.db.query(
            """
            SELECT
                COUNT(*) AS documents,
                SUM(CASE WHEN archived=0 THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN archived=1 THEN 1 ELSE 0 END) AS archived
            FROM work_documents
            """
        )[0]
        types = self.db.query(
            """
            SELECT document_type, COUNT(*) AS count
            FROM work_documents
            WHERE archived=0
            GROUP BY document_type
            ORDER BY count DESC, document_type
            """
        )
        issues = self.db.query(
            """
            SELECT severity, COUNT(*) AS count
            FROM work_document_issues i
            JOIN work_documents d ON d.id=i.document_id
            WHERE i.resolved=0 AND d.archived=0
            GROUP BY severity
            """
        )
        ingest_rows = self.db.query(
            """
            SELECT status, COUNT(*) AS count
            FROM work_document_ingest_log
            GROUP BY status
            """
        )
        recent_failures = self.db.query(
            """
            SELECT id, filename, source, status, document_id,
                   error_type, message, created_at
            FROM work_document_ingest_log
            WHERE status='failed'
            ORDER BY created_at DESC
            LIMIT 20
            """
        )
        return {
            "documents": {
                "total": int(totals["documents"] or 0),
                "active": int(totals["active"] or 0),
                "archived": int(totals["archived"] or 0),
            },
            "types": types,
            "open_issues": {row["severity"]: row["count"] for row in issues},
            "ingest": {
                "by_status": {row["status"]: row["count"] for row in ingest_rows},
                "recent_failures": recent_failures,
            },
            "legacy_rag_documents": self.legacy_rag_count(),
        }

    def _preserve_original(self, item: dict, filename: str, raw: bytes) -> str:
        safe_name = re.sub(
            r"[^A-Za-zА-Яа-яЁё0-9._()\- ]+",
            "_",
            Path(filename).name,
        ).strip(" .") or "document.bin"
        relative = (
            Path("documents")
            / Path(item["archive_path"])
            / item["family_id"]
            / f"v{item['version']}"
            / safe_name
        )
        target = self.db.path.parent / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(raw)
        temporary.replace(target)
        return relative.as_posix()

    @staticmethod
    def _extract_file_text(filename: str, raw: bytes) -> tuple[str, str]:
        suffix = Path(filename).suffix.lower()

        if suffix in {".txt", ".md", ".csv", ".json", ".log"}:
            for encoding in ("utf-8-sig", "utf-8", "cp1251"):
                try:
                    return raw.decode(encoding), f"text:{encoding}"
                except UnicodeDecodeError:
                    continue
            raise ValueError("text file encoding is not supported")

        if suffix == ".docx":
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    xml = archive.read("word/document.xml")
            except (zipfile.BadZipFile, KeyError) as exc:
                raise ValueError("invalid DOCX file") from exc
            root = ElementTree.fromstring(xml)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = []
            for paragraph in root.findall(".//w:p", ns):
                parts = [
                    node.text or ""
                    for node in paragraph.findall(".//w:t", ns)
                ]
                line = "".join(parts).strip()
                if line:
                    paragraphs.append(line)
            text = "\n".join(paragraphs).strip()
            if not text:
                raise ValueError("DOCX contains no extractable text")
            return text, "builtin_docx_xml"

        if suffix == ".xlsx":
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    shared = []
                    if "xl/sharedStrings.xml" in archive.namelist():
                        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                        for item in root.findall(".//x:si", ns):
                            shared.append("".join(
                                node.text or ""
                                for node in item.findall(".//x:t", ns)
                            ))
                    lines = []
                    sheet_names = sorted(
                        name for name in archive.namelist()
                        if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
                    )
                    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    for sheet_name in sheet_names:
                        root = ElementTree.fromstring(archive.read(sheet_name))
                        lines.append(f"[{sheet_name}]")
                        for row in root.findall(".//x:row", ns):
                            values = []
                            for cell in row.findall("x:c", ns):
                                value_node = cell.find("x:v", ns)
                                value = value_node.text if value_node is not None else ""
                                cell_type = cell.get("t")
                                if cell_type == "s" and value.isdigit():
                                    index = int(value)
                                    if 0 <= index < len(shared):
                                        value = shared[index]
                                elif cell_type == "inlineStr":
                                    value = "".join(
                                        node.text or ""
                                        for node in cell.findall(".//x:t", ns)
                                    )
                                values.append(value)
                            if any(str(value).strip() for value in values):
                                lines.append("\t".join(str(value) for value in values))
            except (zipfile.BadZipFile, ElementTree.ParseError) as exc:
                raise ValueError("invalid XLSX file") from exc
            text = "\n".join(lines).strip()
            if not text:
                raise ValueError("XLSX contains no extractable cells")
            return text, "builtin_xlsx_xml"

        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise ValueError(
                    "PDF parser is unavailable: install pypdf"
                ) from exc
            try:
                reader = PdfReader(io.BytesIO(raw))
                pages = [
                    page.extract_text() or ""
                    for page in reader.pages
                ]
            except Exception as exc:
                raise ValueError("PDF text extraction failed") from exc
            text = "\n\n".join(pages).strip()
            if not text:
                raise ValueError(
                    "PDF contains no extractable text; scanned PDF requires OCR"
                )
            return text, "pypdf"

        if suffix == ".doc":
            raise ValueError(
                "legacy .DOC is not safely parsed yet; convert it to DOCX or add a legacy DOC adapter"
            )

        raise ValueError(
            f"unsupported file type: {suffix or 'without extension'}"
        )

    def _classify(self, title: str, text: str, forced_type: str = "") -> str:
        if forced_type:
            if forced_type not in DOCUMENT_TYPES:
                raise ValueError("unsupported document_type")
            return forced_type

        title_l = str(title or "").lower()
        head = str(text or "")[:1400].lower()
        early = str(text or "")[:350].lower()

        def has(value: str, *terms: str) -> bool:
            return any(term in value for term in terms)

        # Prefer title and document heading over references later in the body.
        if has(title_l, "служебная записка") or (
            "служебн" in early and "записк" in early
        ):
            return "service_memo"
        if has(title_l, "счет-оферта", "счёт-оферта") or has(
            early, "счет-оферта", "счёт-оферта"
        ):
            return "invoice_offer"
        if "табель" in title_l or (
            "табель" in early and has(head, "рабоч", "врем")
        ):
            return "timesheet"
        if has(title_l, "птс", "стс", "паспорт транспортного средства") or has(
            early, "паспорт транспортного средства"
        ):
            return "vehicle_document"
        if re.search(r"\bсч[её]т\b", title_l) or re.search(r"\bсч[её]т\b", early):
            return "invoice"
        if re.search(r"\bдоговор\b|\bконтракт\b", title_l) or re.search(
            r"\bдоговор\b|\bконтракт\b", early
        ):
            return "contract"
        if re.search(r"\bакт\b", title_l) or re.search(r"\bакт\b", early):
            return "act"
        if re.search(r"\bприказ\b", title_l) or re.search(r"\bприказ\b", early):
            return "order"

        # Fallback for documents whose heading was lost during extraction.
        if "служебная записка" in head:
            return "service_memo"
        if has(head, "счет-оферта", "счёт-оферта"):
            return "invoice_offer"
        if re.search(r"\bсч[её]т\b", head):
            return "invoice"
        if re.search(r"\bдоговор\b|\bконтракт\b", head):
            return "contract"
        if re.search(r"\bакт\b", head):
            return "act"
        if re.search(r"\bприказ\b", head):
            return "order"
        return "other"

    def _extract_facts(self, text: str) -> list[dict]:
        facts: list[dict] = []
        seen: set[tuple[str, str]] = set()

        def add(kind: str, key: str, value: str, start: int, end: int, confidence: float):
            normalized = _normalized_value(value)
            marker = (kind, normalized)
            if not value or marker in seen:
                return
            seen.add(marker)
            facts.append({
                "type": kind,
                "key": key,
                "value": value,
                "normalized": normalized,
                "confidence": confidence,
                "provenance": {
                    "source": "text",
                    "char_start": start,
                    "char_end": end,
                    "excerpt": text[max(0, start - 40):min(len(text), end + 80)],
                },
            })

        for match in DATE_RE.finditer(text):
            parsed = _parse_date(match.group(1))
            if parsed:
                add("date", "date", parsed, match.start(), match.end(), 0.92)

        number_match = NUMBER_RE.search(text[:3000])
        if number_match:
            add(
                "document_number",
                "document_number",
                number_match.group(1),
                number_match.start(1),
                number_match.end(1),
                0.88,
            )

        for match in MONEY_RE.finditer(text):
            raw = match.group(1).replace("\u00a0", " ").strip()
            add("money", "amount", raw, match.start(1), match.end(1), 0.85)

        for match in VIN_RE.finditer(text):
            add("vehicle", "vin", match.group(0), match.start(), match.end(), 0.97)

        for match in PLATE_RE.finditer(text):
            add(
                "vehicle",
                "registration_number",
                re.sub(r"\s+", "", match.group(0)),
                match.start(),
                match.end(),
                0.94,
            )

        for match in REFERENCE_RE.finditer(text):
            value = f"{match.group(1)} {match.group(2)}"
            add(
                "reference",
                match.group(1).lower().replace("ё", "е"),
                value,
                match.start(),
                match.end(),
                0.82,
            )

        for key, pattern in LABEL_PATTERNS.items():
            for match in pattern.finditer(text):
                add(
                    "party" if key in {"organization", "author", "addressee", "supplier", "counterparty"} else "document",
                    key,
                    match.group(1).strip(),
                    match.start(1),
                    match.end(1),
                    0.84,
                )

        for match in QUANTITY_RE.finditer(text):
            add(
                "quantity",
                "quantity",
                f"{match.group(1)} {match.group(2)}",
                match.start(),
                match.end(),
                0.8,
            )

        for match in VAT_RE.finditer(text):
            value = f"{match.group(1)}%" if match.group(1) else "НДС"
            add(
                "tax",
                "vat",
                value,
                match.start(),
                match.end(),
                0.82,
            )

        request_match = re.search(
            r"(?im)(?:^|[.!?]\s+)(прошу\b[^\n.!?]*(?:[.!?]|$))",
            text,
        )
        if request_match:
            add(
                "action",
                "requested_action",
                request_match.group(1).strip(),
                request_match.start(1),
                request_match.end(1),
                0.83,
            )

        return facts

    def _resolve_family(
        self,
        *,
        document_type: str,
        document_number: str | None,
        title: str,
        explicit_family_id: str,
    ) -> tuple[str, str | None, int]:
        if explicit_family_id:
            rows = self.db.query(
                """
                SELECT id, version
                FROM work_documents
                WHERE family_id=?
                ORDER BY version DESC
                LIMIT 1
                """,
                (explicit_family_id,),
            )
            if rows:
                return explicit_family_id, rows[0]["id"], int(rows[0]["version"]) + 1
            return explicit_family_id, None, 1

        if document_number:
            rows = self.db.query(
                """
                SELECT id, family_id, version
                FROM work_documents
                WHERE document_type=? AND document_number=? AND archived=0
                ORDER BY version DESC
                LIMIT 1
                """,
                (document_type, document_number),
            )
            if rows:
                return rows[0]["family_id"], rows[0]["id"], int(rows[0]["version"]) + 1

        normalized_title = re.sub(r"\W+", "", title.lower())
        rows = self.db.query(
            """
            SELECT id, family_id, version, title
            FROM work_documents
            WHERE document_type=? AND archived=0
            ORDER BY updated_at DESC
            LIMIT 100
            """,
            (document_type,),
        )
        if len(normalized_title) >= 12:
            for row in rows:
                if re.sub(r"\W+", "", row["title"].lower()) == normalized_title:
                    return row["family_id"], row["id"], int(row["version"]) + 1

        return str(uuid4()), None, 1

    def _rebuild_issues(self, document_id: str) -> None:
        doc = self.document(document_id, include_text=True)
        self.db.execute("DELETE FROM work_document_issues WHERE document_id=?", (document_id,))
        issues = []

        def issue(kind: str, severity: str, message: str, details: dict | None = None):
            issues.append((kind, severity, message, details or {}))

        if doc["document_type"] == "other":
            issue(
                "unknown_document_type",
                "warning",
                "Тип документа не определён автоматически.",
            )

        required_number = {"service_memo", "contract", "invoice", "invoice_offer", "order"}
        required_date = {"service_memo", "contract", "invoice", "invoice_offer", "act", "order"}
        if doc["document_type"] in required_number and not doc["document_number"]:
            issue("missing_document_number", "warning", "Не найден номер документа.")
        if doc["document_type"] in required_date and not doc["document_date"]:
            issue("missing_document_date", "warning", "Не найдена дата документа.")

        if doc["document_type"] == "invoice_offer":
            lowered = doc["text_content"].lower()
            if any(term in lowered for term in ("услуг", "выполнен", "работы", "работ ")):
                issue(
                    "invoice_offer_contains_services",
                    "error",
                    "Счёт-оферта содержит признаки услуг/работ; по правилу проекта он должен содержать товар.",
                )

        if doc["document_type"] == "service_memo" and not doc["year"]:
            issue(
                "service_memo_year_unknown",
                "warning",
                "Не удалось определить год для автоматической сортировки служебной записки.",
            )

        filename_year = re.search(
            r"(?<!\d)(19\d{2}|20\d{2})(?!\d)",
            doc.get("original_name") or "",
        )
        if filename_year and doc.get("year") and int(filename_year.group(1)) != int(doc["year"]):
            issue(
                "filename_year_conflict",
                "warning",
                "Год в имени файла отличается от года, найденного в документе.",
                {
                    "filename_year": int(filename_year.group(1)),
                    "document_year": int(doc["year"]),
                },
            )

        with self.db.connect() as db:
            for kind, severity, message, details in issues:
                db.execute(
                    """
                    INSERT INTO work_document_issues(
                        id, document_id, issue_type, severity, message,
                        details_json, resolved, created_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        str(uuid4()),
                        document_id,
                        kind,
                        severity,
                        message,
                        json.dumps(details, ensure_ascii=False),
                        _now(),
                    ),
                )

    def _build_relations(self, document_id: str) -> None:
        facts = self.facts(document_id)
        vehicle_values = {
            item["normalized_value"]
            for item in facts
            if item["fact_type"] == "vehicle"
        }
        reference_facts = [
            item
            for item in facts
            if item["fact_type"] == "reference"
        ]

        for value in vehicle_values:
            rows = self.db.query(
                """
                SELECT DISTINCT f.document_id
                FROM work_document_facts f
                JOIN work_documents d ON d.id=f.document_id
                WHERE f.fact_type='vehicle' AND f.normalized_value=?
                  AND f.document_id!=? AND d.archived=0
                """,
                (value, document_id),
            )
            for row in rows:
                self._upsert_relation(
                    document_id,
                    row["document_id"],
                    "shared_vehicle",
                    0.9,
                    {"normalized_value": value},
                )

        if reference_facts:
            candidates = self.db.query(
                """
                SELECT id, document_number, document_type
                FROM work_documents
                WHERE id!=? AND archived=0 AND document_number!=''
                """,
                (document_id,),
            )
            type_map = {
                "договор": "contract",
                "контракт": "contract",
                "приказ": "order",
                "акт": "act",
                "счет": "invoice",
                "счёт": "invoice",
                "счет-оферта": "invoice_offer",
                "счёт-оферта": "invoice_offer",
            }
            for fact in reference_facts:
                normalized = fact["normalized_value"]
                key = str(fact["fact_key"]).lower()
                prefixes = (
                    "ДОГОВОР",
                    "КОНТРАКТ",
                    "ПРИКАЗ",
                    "АКТ",
                    "СЧЕТ-ОФЕРТА",
                    "СЧЁТ-ОФЕРТА",
                    "СЧЕТ",
                    "СЧЁТ",
                )
                referenced_number = normalized
                for prefix in prefixes:
                    if normalized.startswith(prefix):
                        referenced_number = normalized[len(prefix):]
                        break
                if not referenced_number:
                    continue

                expected_type = type_map.get(key)
                for candidate in candidates:
                    number = _normalized_value(candidate["document_number"])
                    if number != referenced_number:
                        continue
                    if expected_type and candidate["document_type"] != expected_type:
                        continue
                    self._upsert_relation(
                        document_id,
                        candidate["id"],
                        "references",
                        0.99,
                        {
                            "document_number": candidate["document_number"],
                            "reference_key": key,
                            "reference_value": fact["value_text"],
                        },
                    )

    def _cross_document_checks(self, document_id: str) -> None:
        doc = self.document(document_id, include_text=False)
        facts = doc.get("facts", [])
        plates = {
            item["normalized_value"]
            for item in facts
            if item["fact_type"] == "vehicle" and item["fact_key"] == "registration_number"
        }
        vins = {
            item["normalized_value"]
            for item in facts
            if item["fact_type"] == "vehicle" and item["fact_key"] == "vin"
        }

        for plate in plates:
            rows = self.db.query(
                """
                SELECT DISTINCT d.id, d.title
                FROM work_document_facts f
                JOIN work_documents d ON d.id=f.document_id
                WHERE f.fact_type='vehicle'
                  AND f.fact_key='registration_number'
                  AND f.normalized_value=?
                  AND f.document_id!=?
                  AND d.archived=0
                """,
                (plate, document_id),
            )
            for row in rows:
                other_vins = {
                    item["normalized_value"]
                    for item in self.facts(row["id"])
                    if item["fact_type"] == "vehicle" and item["fact_key"] == "vin"
                }
                if vins and other_vins and vins.isdisjoint(other_vins):
                    self._add_issue(
                        document_id,
                        "vehicle_identity_conflict",
                        "error",
                        "Один госномер связан с разными VIN в документах.",
                        {
                            "registration_number": plate,
                            "current_vins": sorted(vins),
                            "other_document_id": row["id"],
                            "other_document_title": row["title"],
                            "other_vins": sorted(other_vins),
                        },
                    )

        for relation in self.relations(document_id):
            if relation["relation_type"] != "references":
                continue
            target = self.document(relation["target_document_id"], include_text=False)
            if (
                doc.get("document_date")
                and target.get("document_date")
                and doc["document_date"] < target["document_date"]
                and doc["document_type"] in {"invoice", "invoice_offer", "act"}
                and target["document_type"] == "contract"
            ):
                self._add_issue(
                    document_id,
                    "reference_date_conflict",
                    "warning",
                    "Документ датирован раньше договора, на который он ссылается.",
                    {
                        "document_date": doc["document_date"],
                        "contract_date": target["document_date"],
                        "contract_document_id": target["id"],
                        "contract_number": target.get("document_number"),
                    },
                )

            current_suppliers = {
                item["normalized_value"]
                for item in facts
                if item["fact_type"] == "party"
                and item["fact_key"] in {"supplier", "counterparty"}
            }
            target_suppliers = {
                item["normalized_value"]
                for item in target.get("facts", [])
                if item["fact_type"] == "party"
                and item["fact_key"] in {"supplier", "counterparty"}
            }
            if (
                current_suppliers
                and target_suppliers
                and current_suppliers.isdisjoint(target_suppliers)
            ):
                self._add_issue(
                    document_id,
                    "counterparty_conflict",
                    "error",
                    "Контрагент в документе отличается от контрагента связанного договора.",
                    {
                        "current": sorted(current_suppliers),
                        "contract": sorted(target_suppliers),
                        "contract_document_id": target["id"],
                    },
                )

    def _compare_versions(self, document_id: str, previous_id: str) -> None:
        current = self.document(document_id, include_text=False)
        previous = self.document(previous_id, include_text=False)
        changes = {}
        for key in ("document_number", "document_date", "document_type"):
            if current.get(key) != previous.get(key):
                changes[key] = {
                    "previous": previous.get(key),
                    "current": current.get(key),
                }
        if changes:
            self._add_issue(
                document_id,
                "version_core_fields_changed",
                "warning",
                "В новой версии изменились основные реквизиты документа.",
                changes,
            )

    def _upsert_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        score: float,
        evidence: dict,
    ) -> None:
        if source_id == target_id:
            return
        self.db.execute(
            """
            INSERT INTO work_document_relations(
                id, source_document_id, target_document_id,
                relation_type, score, evidence_json, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_document_id, target_document_id, relation_type)
            DO UPDATE SET
                score=excluded.score,
                evidence_json=excluded.evidence_json
            """,
            (
                str(uuid4()),
                source_id,
                target_id,
                relation_type,
                float(score),
                json.dumps(evidence, ensure_ascii=False),
                _now(),
            ),
        )

    def _sync_status(self, document_id: str) -> None:
        rows = self.db.query(
            """
            SELECT severity, COUNT(*) AS count
            FROM work_document_issues
            WHERE document_id=? AND resolved=0
            GROUP BY severity
            """,
            (document_id,),
        )
        counts = {row["severity"]: int(row["count"]) for row in rows}
        status = (
            "error"
            if counts.get("error", 0)
            else "attention"
            if counts.get("warning", 0)
            else "studied"
        )
        self.db.execute(
            "UPDATE work_documents SET status=?, updated_at=? WHERE id=?",
            (status, _now(), document_id),
        )

    def _add_issue(
        self,
        document_id: str,
        issue_type: str,
        severity: str,
        message: str,
        details: dict,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO work_document_issues(
                id, document_id, issue_type, severity, message,
                details_json, resolved, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                str(uuid4()),
                document_id,
                issue_type,
                severity,
                message,
                json.dumps(details, ensure_ascii=False),
                _now(),
            ),
        )

    @staticmethod
    def _first_fact(facts: list[dict], fact_type: str) -> str | None:
        for fact in facts:
            if fact["type"] == fact_type:
                return fact["value"]
        return None

    @staticmethod
    def _infer_year(facts: list[dict], text: str) -> int | None:
        years = []
        for fact in facts:
            if fact["type"] == "date" and re.match(r"^\d{4}-", fact["value"]):
                years.append(int(fact["value"][:4]))
        if years:
            return Counter(years).most_common(1)[0][0]
        match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
        return int(match.group(1)) if match else None

    @staticmethod
    def _archive_path(document_type: str, year: int | None) -> str:
        root = TYPE_ARCHIVES.get(document_type, TYPE_ARCHIVES["other"])
        return f"{root}/{year if year else 'Без года'}"

    @staticmethod
    def _structure_signature(document_type: str, text: str, facts: list[dict]) -> dict:
        lines = text.splitlines()
        words = WORD_RE.findall(text)
        fact_counts = Counter(fact["type"] for fact in facts)
        return {
            "document_type": document_type,
            "line_count": len(lines),
            "nonempty_line_count": sum(1 for line in lines if line.strip()),
            "word_count": len(words),
            "digit_count": sum(ch.isdigit() for ch in text),
            "uppercase_word_count": sum(1 for word in words if len(word) > 2 and word.isupper()),
            "fact_counts": dict(sorted(fact_counts.items())),
            "line_length_buckets": [
                sum(1 for line in lines if 0 < len(line) <= 40),
                sum(1 for line in lines if 40 < len(line) <= 120),
                sum(1 for line in lines if len(line) > 120),
            ],
        }

    @staticmethod
    def _passport(
        *,
        document_id: str,
        family_id: str,
        version: int,
        title: str,
        original_name: str,
        document_type: str,
        document_number: str | None,
        document_date: str | None,
        year: int | None,
        archive_path: str,
        facts: list[dict],
        content_hash: str,
    ) -> dict:
        return {
            "document_id": document_id,
            "family_id": family_id,
            "version": version,
            "title": title,
            "original_name": original_name,
            "type": document_type,
            "type_label": DOCUMENT_TYPES.get(document_type, document_type),
            "number": document_number,
            "date": document_date,
            "year": year,
            "archive_path": archive_path,
            "fact_count": len(facts),
            "content_sha256": content_hash,
        }

    @staticmethod
    def _dna(
        *,
        text: str,
        document_type: str,
        content_hash: str,
        normalized_hash: str,
        structure_hash: str,
        structure: dict,
        facts: list[dict],
    ) -> dict:
        fact_material = [
            (fact["type"], fact["key"], fact["normalized"])
            for fact in facts
        ]
        fact_fingerprint = _sha256(
            json.dumps(sorted(fact_material), ensure_ascii=False)
        )
        return {
            "version": "1.1",
            "document_type": document_type,
            "content_sha256": content_hash,
            "normalized_sha256": normalized_hash,
            "structure_sha256": structure_hash,
            "fact_fingerprint": fact_fingerprint,
            "structure": structure,
            "identifiers": {
                "dates": [f["value"] for f in facts if f["type"] == "date"],
                "document_numbers": [
                    f["value"] for f in facts if f["type"] == "document_number"
                ],
                "vehicle_ids": [
                    f["value"] for f in facts if f["type"] == "vehicle"
                ],
                "references": [
                    f["value"] for f in facts if f["type"] == "reference"
                ],
            },
            "text_length": len(text),
        }

    @staticmethod
    def _decode_document(item: dict) -> dict:
        item["passport"] = json.loads(item.pop("passport_json") or "{}")
        item["dna"] = json.loads(item.pop("dna_json") or "{}")
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        item["archived"] = bool(item["archived"])
        item["passport"]["status"] = item.get("status")
        item["passport"]["archived"] = item["archived"]
        return item
