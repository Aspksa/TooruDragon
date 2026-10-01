from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from .database import Database


_DOCUMENT_TYPES = {
    "invoice_offer",
    "contract",
    "invoice",
    "service_note",
    "defect_report",
    "specification",
    "act",
    "unknown",
}
_SUBJECT_TYPES = {"goods", "services", "mixed", "unknown"}
_ASSET_SCOPES = {"garage", "external", "unresolved", "general"}
_FACT_STATUSES = {"candidate", "confirmed", "superseded", "rejected"}

_GOODS_WORDS = (
    "товар", "поставк", "запчаст", "запасн", "детал", "комплектующ",
    "материал", "оборудован", "артикул", "номенклатур", "купл", "продаж",
)
_SERVICE_WORDS = (
    "услуг", "работ", "ремонт", "диагност", "монтаж", "демонтаж",
    "обслужив", "техническое обслуживание", "то ", "дефектов",
)
_VEHICLE_WORDS = (
    "автомоб", "машин", "транспортн", "госномер", "гос. номер", "vin",
    "шасси", "двигател", "пробег",
)
_EXTERNAL_WORDS = (
    "сторонн", "арендован", "заказчика", "клиента", "не состоит в гараже",
    "внешняя техника", "внешней техники",
)
_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"игнорир\w*\s+(?:все\s+)?(?:предыдущ|системн)", re.IGNORECASE),
    re.compile(r"системн\w*\s+(?:промпт|инструкц)", re.IGNORECASE),
    re.compile(r"выполни\w*\s+(?:команд|инструкц)", re.IGNORECASE),
    re.compile(r"ignore\s+(?:all\s+)?previous", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
)
_VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
_PLATE_RE = re.compile(r"\b[АВЕКМНОРСТУХABEKMHOPCTYX]\s?\d{3}\s?[АВЕКМНОРСТУХABEKMHOPCTYX]{2}\s?\d{2,3}\b", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalized(text: str) -> str:
    return " ".join(str(text or "").lower().replace("ё", "е").split())


def _score_words(text: str, words: tuple[str, ...]) -> int:
    return sum(1 for word in words if word in text)


class DocumentIntelligence:
    """Rule-first document understanding and safe knowledge intake for TooruDragon.

    The classifier intentionally separates document type, purchase subject and asset
    relation. A document is never assumed to belong to a Garage vehicle merely because
    it mentions spare parts, repairs or a vehicle identifier.
    """

    def __init__(self, database: Database | None = None):
        self.db = database or Database()

    def analyze(
        self,
        text: str,
        *,
        title: str | None = None,
        source: str = "manual",
        metadata: dict | None = None,
    ) -> dict:
        raw = str(text or "").strip()
        if not raw:
            raise ValueError("document text is required")
        metadata = metadata if isinstance(metadata, dict) else {}
        normalized = _normalized(raw)

        document_type = self._document_type(normalized)
        goods_score = _score_words(normalized, _GOODS_WORDS)
        services_score = _score_words(normalized, _SERVICE_WORDS)
        subject_type = self._subject_type(
            document_type,
            goods_score=goods_score,
            services_score=services_score,
        )

        vins = list(dict.fromkeys(match.upper() for match in _VIN_RE.findall(raw)))
        plates = list(dict.fromkeys(match.upper().replace(" ", "") for match in _PLATE_RE.findall(raw)))
        vehicle_signals = _score_words(normalized, _VEHICLE_WORDS) + len(vins) + len(plates)
        asset_scope, garage_vehicle_id = self._asset_scope(
            normalized,
            metadata,
            vehicle_signals=vehicle_signals,
        )

        warnings: list[str] = []
        if document_type == "invoice_offer" and services_score:
            warnings.append("invoice_offer_contains_service_signals")
        if asset_scope == "unresolved":
            warnings.append("vehicle_relation_unresolved")
        if document_type == "unknown":
            warnings.append("document_type_unknown")
        if subject_type == "unknown" and document_type in {"contract", "invoice", "invoice_offer"}:
            warnings.append("subject_type_unknown")

        injection_matches = []
        for pattern in _PROMPT_INJECTION_PATTERNS:
            match = pattern.search(raw)
            if match:
                injection_matches.append(match.group(0)[:120])
        if injection_matches:
            warnings.append("prompt_injection_suspected")

        confidence = self._confidence(
            document_type=document_type,
            subject_type=subject_type,
            goods_score=goods_score,
            services_score=services_score,
            warnings=warnings,
        )
        requires_review = bool(
            injection_matches
            or document_type == "unknown"
            or "invoice_offer_contains_service_signals" in warnings
        )

        return {
            "analysis_id": str(uuid4()),
            "title": title,
            "source": str(source or "manual"),
            "document_type": document_type,
            "subject_type": subject_type,
            "asset_scope": asset_scope,
            "garage_vehicle_id": garage_vehicle_id,
            "requires_garage_match": bool(metadata.get("require_garage_match", False)),
            "confidence": confidence,
            "requires_review": requires_review,
            "warnings": warnings,
            "signals": {
                "goods_score": goods_score,
                "services_score": services_score,
                "vehicle_signals": vehicle_signals,
            },
            "extracted": {
                "vins": vins,
                "plates": plates,
            },
            "security": {
                "prompt_injection_suspected": bool(injection_matches),
                "matches": injection_matches,
                "safe_for_automatic_learning": not bool(injection_matches),
            },
            "workflow": self._workflow(document_type, subject_type),
            "knowledge_candidates": self._knowledge_candidates(
                document_type=document_type,
                subject_type=subject_type,
                asset_scope=asset_scope,
                garage_vehicle_id=garage_vehicle_id,
                vins=vins,
                plates=plates,
                confidence=confidence,
            ),
        }

    def store_analysis(self, analysis: dict, *, document_id: str | None = None) -> dict:
        if not isinstance(analysis, dict):
            raise TypeError("analysis must be an object")
        analysis_id = str(analysis.get("analysis_id") or uuid4())
        now = _now()
        warnings = list(analysis.get("warnings") or [])
        extracted = dict(analysis.get("extracted") or {})
        security = dict(analysis.get("security") or {})
        signals = dict(analysis.get("signals") or {})
        payload = {
            "signals": signals,
            "security": security,
            "workflow": analysis.get("workflow"),
        }
        self.db.execute(
            """
            INSERT INTO ai_document_analysis(
                id, document_id, title, source, document_type, subject_type,
                asset_scope, garage_vehicle_id, confidence, requires_review,
                warnings_json, extracted_json, analysis_json, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                document_id=excluded.document_id,
                title=excluded.title,
                source=excluded.source,
                document_type=excluded.document_type,
                subject_type=excluded.subject_type,
                asset_scope=excluded.asset_scope,
                garage_vehicle_id=excluded.garage_vehicle_id,
                confidence=excluded.confidence,
                requires_review=excluded.requires_review,
                warnings_json=excluded.warnings_json,
                extracted_json=excluded.extracted_json,
                analysis_json=excluded.analysis_json,
                updated_at=excluded.updated_at
            """,
            (
                analysis_id,
                document_id,
                analysis.get("title"),
                str(analysis.get("source") or "manual"),
                str(analysis.get("document_type") or "unknown"),
                str(analysis.get("subject_type") or "unknown"),
                str(analysis.get("asset_scope") or "general"),
                analysis.get("garage_vehicle_id"),
                float(analysis.get("confidence") or 0.0),
                1 if analysis.get("requires_review") else 0,
                json.dumps(warnings, ensure_ascii=False),
                json.dumps(extracted, ensure_ascii=False),
                json.dumps(payload, ensure_ascii=False),
                now,
                now,
            ),
        )
        result = dict(analysis)
        result["analysis_id"] = analysis_id
        result["document_id"] = document_id
        result["stored_at"] = now
        return result

    def learn_candidates(
        self,
        analysis: dict,
        *,
        scope: str = "work_documents",
        document_id: str | None = None,
    ) -> list[dict]:
        security = analysis.get("security") if isinstance(analysis, dict) else {}
        if isinstance(security, dict) and security.get("prompt_injection_suspected"):
            return []

        items = []
        now = _now()
        for candidate in analysis.get("knowledge_candidates", []):
            confidence = max(0.0, min(float(candidate.get("confidence", 0.0)), 1.0))
            fact_id = str(uuid4())
            value = candidate.get("value")
            provenance = {
                "analysis_id": analysis.get("analysis_id"),
                "document_id": document_id,
                "title": analysis.get("title"),
            }
            self.db.execute(
                """
                INSERT INTO ai_knowledge_facts(
                    id, scope, subject_type, subject_id, fact_key, value_json,
                    source, confidence, status, provenance_json, valid_from,
                    valid_to, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?, NULL, NULL, ?, ?)
                """,
                (
                    fact_id,
                    str(scope or "work_documents"),
                    str(candidate.get("subject_type") or "document"),
                    candidate.get("subject_id"),
                    str(candidate.get("fact_key") or "fact"),
                    json.dumps(value, ensure_ascii=False),
                    "document_analysis",
                    confidence,
                    json.dumps(provenance, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            items.append({
                "id": fact_id,
                "fact_key": candidate.get("fact_key"),
                "value": value,
                "confidence": confidence,
                "status": "candidate",
            })
        return items

    def facts(
        self,
        *,
        scope: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        clauses = []
        params: list = []
        if scope:
            clauses.append("scope=?")
            params.append(scope)
        if status:
            if status not in _FACT_STATUSES:
                raise ValueError("unsupported fact status")
            clauses.append("status=?")
            params.append(status)
        sql = "SELECT * FROM ai_knowledge_facts"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        result = []
        for row in self.db.query(sql, tuple(params)):
            item = dict(row)
            item["value"] = json.loads(item.pop("value_json") or "null")
            item["provenance"] = json.loads(item.pop("provenance_json") or "{}")
            result.append(item)
        return result

    def analyses(self, limit: int = 100) -> list[dict]:
        rows = self.db.query(
            """
            SELECT id, document_id, title, source, document_type, subject_type,
                   asset_scope, garage_vehicle_id, confidence, requires_review,
                   warnings_json, extracted_json, created_at, updated_at
            FROM ai_document_analysis
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 1000)),),
        )
        result = []
        for row in rows:
            item = dict(row)
            item["requires_review"] = bool(item["requires_review"])
            item["warnings"] = json.loads(item.pop("warnings_json") or "[]")
            item["extracted"] = json.loads(item.pop("extracted_json") or "{}")
            result.append(item)
        return result

    def analytics(self) -> dict:
        rows = self.db.query(
            """
            SELECT document_type, subject_type, asset_scope, requires_review
            FROM ai_document_analysis
            """
        )
        document_types = Counter(row["document_type"] for row in rows)
        subject_types = Counter(row["subject_type"] for row in rows)
        asset_scopes = Counter(row["asset_scope"] for row in rows)
        review_count = sum(1 for row in rows if row["requires_review"])
        fact_rows = self.db.query(
            "SELECT status, COUNT(*) AS n FROM ai_knowledge_facts GROUP BY status"
        )
        return {
            "documents": len(rows),
            "document_types": dict(document_types),
            "subject_types": dict(subject_types),
            "asset_scopes": dict(asset_scopes),
            "requires_review": review_count,
            "knowledge_facts": {row["status"]: row["n"] for row in fact_rows},
        }

    @staticmethod
    def _document_type(text: str) -> str:
        if re.search(r"счет\s*[-–—]?\s*оферт", text):
            return "invoice_offer"
        if "договор" in text:
            return "contract"
        if "служебная записка" in text or "служебк" in text:
            return "service_note"
        if "дефектов" in text or "дефектный акт" in text:
            return "defect_report"
        if "спецификац" in text:
            return "specification"
        if re.search(r"\bсчет\b", text):
            return "invoice"
        if "акт" in text:
            return "act"
        return "unknown"

    @staticmethod
    def _subject_type(document_type: str, *, goods_score: int, services_score: int) -> str:
        if document_type == "invoice_offer":
            return "goods"
        if goods_score and services_score:
            return "mixed"
        if goods_score:
            return "goods"
        if services_score:
            return "services"
        return "unknown"

    @staticmethod
    def _asset_scope(text: str, metadata: dict, *, vehicle_signals: int) -> tuple[str, str | None]:
        garage_vehicle_id = str(metadata.get("garage_vehicle_id") or "").strip() or None
        if garage_vehicle_id:
            return "garage", garage_vehicle_id

        explicit = str(metadata.get("asset_scope") or "").strip().lower()
        if explicit in _ASSET_SCOPES:
            return explicit, None
        if explicit in {"none", "not_applicable", "not-applicable"}:
            return "general", None
        if any(word in text for word in _EXTERNAL_WORDS):
            return "external", None
        if vehicle_signals:
            return "unresolved", None
        return "general", None

    @staticmethod
    def _confidence(
        *,
        document_type: str,
        subject_type: str,
        goods_score: int,
        services_score: int,
        warnings: list[str],
    ) -> float:
        score = 0.45
        if document_type != "unknown":
            score += 0.25
        if subject_type != "unknown":
            score += 0.15
        score += min(0.10, (goods_score + services_score) * 0.02)
        if "invoice_offer_contains_service_signals" in warnings:
            score -= 0.20
        if "prompt_injection_suspected" in warnings:
            score -= 0.25
        return round(max(0.05, min(score, 0.99)), 3)

    @staticmethod
    def _workflow(document_type: str, subject_type: str) -> str:
        if document_type == "invoice_offer":
            return "purchase.goods.invoice_offer"
        if document_type == "contract":
            return f"contract.{subject_type}"
        if document_type == "invoice":
            return f"purchase.{subject_type}.invoice"
        if document_type == "defect_report":
            return "maintenance.defect_report"
        if document_type == "service_note":
            return "documents.service_note"
        if document_type == "specification":
            return "documents.specification"
        if document_type == "act":
            return f"documents.act.{subject_type}"
        return "documents.review"

    @staticmethod
    def _knowledge_candidates(
        *,
        document_type: str,
        subject_type: str,
        asset_scope: str,
        garage_vehicle_id: str | None,
        vins: list[str],
        plates: list[str],
        confidence: float,
    ) -> list[dict]:
        items = [
            {
                "subject_type": "document",
                "subject_id": None,
                "fact_key": "document_type",
                "value": document_type,
                "confidence": confidence,
            },
            {
                "subject_type": "document",
                "subject_id": None,
                "fact_key": "subject_type",
                "value": subject_type,
                "confidence": confidence,
            },
            {
                "subject_type": "document",
                "subject_id": None,
                "fact_key": "asset_scope",
                "value": asset_scope,
                "confidence": confidence,
            },
        ]
        if garage_vehicle_id:
            items.append({
                "subject_type": "garage_vehicle",
                "subject_id": garage_vehicle_id,
                "fact_key": "document_relation",
                "value": "explicit",
                "confidence": 1.0,
            })
        for vin in vins:
            items.append({
                "subject_type": "asset",
                "subject_id": vin,
                "fact_key": "vin_mentioned",
                "value": True,
                "confidence": 0.95,
            })
        for plate in plates:
            items.append({
                "subject_type": "asset",
                "subject_id": plate,
                "fact_key": "plate_mentioned",
                "value": True,
                "confidence": 0.9,
            })
        return items
