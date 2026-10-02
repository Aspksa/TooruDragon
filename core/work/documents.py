from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
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

        if previous_id:
            self._upsert_relation(
                document_id,
                previous_id,
                "supersedes",
                1.0,
                {"family_id": family_id, "version": version},
            )
            self._compare_versions(document_id, previous_id)

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
            (like, like, like, like, like, max(1, min(int(limit), 200))),
        )
        return [self.document(row["id"], include_text=False) for row in rows]

    def archive(self, document_id: str) -> dict:
        self.document(document_id, include_text=False)
        self.db.execute(
            """
            UPDATE work_documents
            SET archived=1, status='archived', updated_at=?
            WHERE id=?
            """,
            (_now(), document_id),
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
        return {
            "documents": {
                "total": int(totals["documents"] or 0),
                "active": int(totals["active"] or 0),
                "archived": int(totals["archived"] or 0),
            },
            "types": types,
            "open_issues": {row["severity"]: row["count"] for row in issues},
        }

    def _classify(self, title: str, text: str, forced_type: str = "") -> str:
        if forced_type:
            if forced_type not in DOCUMENT_TYPES:
                raise ValueError("unsupported document_type")
            return forced_type

        sample = f"{title}\n{text[:5000]}".lower()
        if "служебная записка" in sample or "служебн" in sample and "записк" in sample:
            return "service_memo"
        if "счет-оферта" in sample or "счёт-оферта" in sample:
            return "invoice_offer"
        if "договор" in sample or "контракт" in sample:
            return "contract"
        if re.search(r"\bсч[её]т\b", sample):
            return "invoice"
        if re.search(r"\bакт\b", sample):
            return "act"
        if re.search(r"\bприказ\b", sample):
            return "order"
        if "табель" in sample and ("рабоч" in sample or "врем" in sample):
            return "timesheet"
        if any(term in sample for term in ("птс", "стс", "паспорт транспортного средства")):
            return "vehicle_document"
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
        references = {
            item["normalized_value"]
            for item in facts
            if item["fact_type"] == "reference"
        }

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

        if references:
            candidates = self.db.query(
                """
                SELECT id, document_number, document_type
                FROM work_documents
                WHERE id!=? AND archived=0 AND document_number!=''
                """,
                (document_id,),
            )
            for candidate in candidates:
                number = _normalized_value(candidate["document_number"])
                if any(number and number in reference for reference in references):
                    self._upsert_relation(
                        document_id,
                        candidate["id"],
                        "references",
                        0.97,
                        {"document_number": candidate["document_number"]},
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
        return {
            "version": "1.0",
            "document_type": document_type,
            "content_sha256": content_hash,
            "normalized_sha256": normalized_hash,
            "structure_sha256": structure_hash,
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
        return item
