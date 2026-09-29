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


class AIMemoryStore:
    def __init__(self, database: Database | None = None):
        self.db = database or Database()

    def ensure_conversation(
        self,
        conversation_id: str | None = None,
        *,
        title: str | None = None,
    ) -> str:
        conversation_id = (conversation_id or "").strip() or str(uuid4())
        rows = self.db.query(
            "SELECT id FROM ai_conversations WHERE id=?",
            (conversation_id,),
        )
        if not rows:
            now = _now()
            self.db.execute(
                """
                INSERT INTO ai_conversations(id, title, created_at, updated_at)
                VALUES(?, ?, ?, ?)
                """,
                (conversation_id, title, now, now),
            )
        return conversation_id

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        trace_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("unsupported message role")
        if not content.strip():
            raise ValueError("message content is required")
        self.ensure_conversation(conversation_id)
        message_id = str(uuid4())
        created_at = _now()
        self.db.execute(
            """
            INSERT INTO ai_messages(
                id, conversation_id, role, content, provider, model,
                trace_id, metadata_json, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                conversation_id,
                role,
                content,
                provider,
                model,
                trace_id,
                json.dumps(metadata or {}, ensure_ascii=False),
                created_at,
            ),
        )
        self.db.execute(
            "UPDATE ai_conversations SET updated_at=? WHERE id=?",
            (created_at, conversation_id),
        )
        return {
            "id": message_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "provider": provider,
            "model": model,
            "trace_id": trace_id,
            "metadata": metadata or {},
            "created_at": created_at,
        }

    def history(self, conversation_id: str, limit: int = 24) -> list[dict]:
        rows = self.db.query(
            """
            SELECT id, conversation_id, role, content, provider, model,
                   trace_id, metadata_json, created_at
            FROM ai_messages
            WHERE conversation_id=?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, max(1, min(int(limit), 200))),
        )
        rows.reverse()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            result.append(item)
        return result

    def remember(
        self,
        scope: str,
        content: str,
        *,
        source: str = "manual",
        metadata: dict | None = None,
    ) -> dict:
        if not scope.strip() or not content.strip():
            raise ValueError("scope and content are required")
        memory_id = str(uuid4())
        created_at = _now()
        self.db.execute(
            """
            INSERT INTO ai_memory_items(id, scope, content, source, metadata_json, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                scope.strip(),
                content.strip(),
                source,
                json.dumps(metadata or {}, ensure_ascii=False),
                created_at,
            ),
        )
        return {
            "id": memory_id,
            "scope": scope.strip(),
            "content": content.strip(),
            "source": source,
            "metadata": metadata or {},
            "created_at": created_at,
        }

    def retrieve(
        self,
        query: str,
        *,
        scope: str | None = None,
        limit: int = 6,
        scan_limit: int = 500,
    ) -> list[dict]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []

        clauses = []
        params: list = []
        if scope:
            clauses.append("scope=?")
            params.append(scope)

        sql = """
            SELECT id, scope, content, source, metadata_json, created_at
            FROM ai_memory_items
        """
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(scan_limit), 2000)))

        scored = []
        for row in self.db.query(sql, tuple(params)):
            item = dict(row)
            content_tokens = _tokens(item["content"])
            overlap = len(query_tokens & content_tokens)
            if not overlap:
                continue
            union = len(query_tokens | content_tokens)
            jaccard = overlap / max(1, union)
            density = overlap / math.sqrt(max(1, len(content_tokens)))
            score = jaccard + density * 0.15
            item["score"] = round(score, 6)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            scored.append(item)

        scored.sort(key=lambda x: (x["score"], x["created_at"]), reverse=True)
        return scored[: max(1, min(int(limit), 50))]

    def conversations(self, limit: int = 50) -> list[dict]:
        return self.db.query(
            """
            SELECT id, title, created_at, updated_at
            FROM ai_conversations
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 200)),),
        )
