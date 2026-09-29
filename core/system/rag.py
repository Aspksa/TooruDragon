from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from uuid import uuid4

from .database import Database


_TOKEN_RE = re.compile(r"[\wа-яё]+", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text or "")
        if len(token) >= 2
    }


class RAGIndex:
    def __init__(
        self,
        database: Database | None = None,
        *,
        chunk_size: int = 1200,
        chunk_overlap: int = 150,
    ):
        self.db = database or Database()
        self.chunk_size = max(200, int(chunk_size))
        self.chunk_overlap = max(0, min(int(chunk_overlap), self.chunk_size // 2))

    def _chunk(self, text: str) -> list[str]:
        normalized = "\n".join(
            line.strip()
            for line in str(text or "").replace("\r\n", "\n").split("\n")
        ).strip()
        if not normalized:
            return []

        chunks = []
        start = 0
        while start < len(normalized):
            end = min(len(normalized), start + self.chunk_size)
            if end < len(normalized):
                preferred = normalized.rfind("\n", start, end)
                if preferred <= start + self.chunk_size // 3:
                    preferred = normalized.rfind(" ", start, end)
                if preferred > start:
                    end = preferred

            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            next_start = max(start + 1, end - self.chunk_overlap)
            start = next_start
        return chunks

    def ingest(
        self,
        text: str,
        *,
        title: str | None = None,
        source: str = "manual",
        metadata: dict | None = None,
        document_id: str | None = None,
    ) -> dict:
        text = str(text or "").strip()
        if not text:
            raise ValueError("document text is required")

        chunks = self._chunk(text)
        if not chunks:
            raise ValueError("document produced no chunks")

        document_id = (document_id or "").strip() or str(uuid4())
        created_at = _now()
        with self.db.connect() as db:
            db.execute(
                """
                INSERT INTO ai_documents(
                    id, title, source, metadata_json, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    source=excluded.source,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    document_id,
                    title,
                    source,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    created_at,
                    created_at,
                ),
            )
            db.execute(
                "DELETE FROM ai_document_chunks WHERE document_id=?",
                (document_id,),
            )
            for index, content in enumerate(chunks):
                db.execute(
                    """
                    INSERT INTO ai_document_chunks(
                        id, document_id, chunk_index, content, created_at
                    )
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        document_id,
                        index,
                        content,
                        created_at,
                    ),
                )

        return {
            "id": document_id,
            "title": title,
            "source": source,
            "chunk_count": len(chunks),
            "created_at": created_at,
        }

    def search(
        self,
        query: str,
        *,
        limit: int = 6,
        scan_limit: int = 1000,
    ) -> list[dict]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []

        rows = self.db.query(
            """
            SELECT
                c.id,
                c.document_id,
                c.chunk_index,
                c.content,
                c.created_at,
                d.title,
                d.source,
                d.metadata_json
            FROM ai_document_chunks AS c
            JOIN ai_documents AS d ON d.id = c.document_id
            ORDER BY c.created_at DESC
            LIMIT ?
            """,
            (max(1, min(int(scan_limit), 5000)),),
        )

        scored = []
        for row in rows:
            item = dict(row)
            content_tokens = _tokens(item["content"])
            overlap = len(query_tokens & content_tokens)
            if not overlap:
                continue
            union = len(query_tokens | content_tokens)
            jaccard = overlap / max(1, union)
            density = overlap / math.sqrt(max(1, len(content_tokens)))
            item["score"] = round(jaccard + density * 0.15, 6)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            scored.append(item)

        scored.sort(key=lambda x: (x["score"], x["created_at"]), reverse=True)
        return scored[: max(1, min(int(limit), 50))]

    def documents(self, limit: int = 100) -> list[dict]:
        return self.db.query(
            """
            SELECT
                d.id,
                d.title,
                d.source,
                d.metadata_json,
                d.created_at,
                d.updated_at,
                COUNT(c.id) AS chunk_count
            FROM ai_documents AS d
            LEFT JOIN ai_document_chunks AS c ON c.document_id = d.id
            GROUP BY d.id
            ORDER BY d.updated_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        )
