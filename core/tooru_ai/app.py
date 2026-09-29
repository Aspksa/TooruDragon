from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route
from core.system.ai_memory import AIMemoryStore
from core.system.chat_runtime import ChatConfig, ChatRuntime
from core.system.model_router import ModelProviderError, ModelRouter
from core.system.rag import RAGIndex
from core.system.secrets import SecretStore

CAPABILITIES = [
    "dialog",
    "stateless_inference",
    "memory",
    "models",
    "tools",
    "ai_orchestration",
    "chat_runtime",
    "retrieval",
]

runtime = CoreRuntime(
    "tooru_ai",
    "Основное AI-ядро Тору: диалог, память, модели и инструменты",
    capabilities=CAPABILITIES,
)

ai_cfg = runtime.config.get("ai_runtime", {})
secrets = SecretStore()
memory = AIMemoryStore(runtime.db)
model_router = ModelRouter(
    ai_cfg.get("model_router", {}),
    secrets=secrets,
)
rag_cfg = ai_cfg.get("rag", {})
rag = RAGIndex(
    runtime.db,
    chunk_size=int(rag_cfg.get("chunk_size", 1200)),
    chunk_overlap=int(rag_cfg.get("chunk_overlap", 150)),
) if bool(rag_cfg.get("enabled", True)) else None
chat_runtime = ChatRuntime(
    model_router,
    memory,
    ChatConfig(
        system_prompt=str(ai_cfg.get("system_prompt", "")),
        history_limit=int(ai_cfg.get("history_limit", 24)),
        retrieval_limit=int(ai_cfg.get("retrieval_limit", 6)),
        rag_limit=int(ai_cfg.get("rag_limit", 6)),
        memory_scope=str(ai_cfg.get("memory_scope", "global")),
    ),
    rag=rag,
)


def capabilities(_request):
    return 200, {
        "service": "tooru_ai",
        "version": runtime.version,
        "capabilities": CAPABILITIES,
    }


def runtime_status(_request):
    return 200, {
        "service": "tooru_ai",
        "version": runtime.version,
        "runtime": chat_runtime.status(),
    }


def models(_request):
    return 200, {
        "service": "tooru_ai",
        "models": model_router.status(),
    }


def inference(request):
    payload = request.json if isinstance(request.json, dict) else {}
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        return 400, {"error": "prompt_required"}
    max_chars = int(ai_cfg.get("max_message_chars", 65536))
    if len(prompt) > max_chars:
        return 413, {"error": "prompt_too_large", "max_chars": max_chars}

    messages = []
    system_prompt = str(payload.get("system_prompt", "")).strip()
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        result = model_router.chat(
            messages,
            provider=payload.get("provider"),
            model=payload.get("model"),
            temperature=(
                float(payload["temperature"])
                if payload.get("temperature") is not None
                else None
            ),
            max_tokens=(
                int(payload["max_tokens"])
                if payload.get("max_tokens") is not None
                else None
            ),
        )
    except ModelProviderError as exc:
        return 503, {
            "error": "provider_unavailable",
            "message": str(exc),
            "models": model_router.status(),
        }
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_inference_request", "message": str(exc)}

    return 200, {
        "service": "tooru_ai",
        "inference": result,
    }


def chat(request):
    payload = request.json if isinstance(request.json, dict) else {}
    message = str(payload.get("message", "")).strip()
    if not message:
        return 400, {"error": "message_required"}
    max_chars = int(ai_cfg.get("max_message_chars", 65536))
    if len(message) > max_chars:
        return 413, {"error": "message_too_large", "max_chars": max_chars}

    try:
        result = chat_runtime.chat(
            message,
            conversation_id=payload.get("conversation_id"),
            provider=payload.get("provider"),
            model=payload.get("model"),
            temperature=(
                float(payload["temperature"])
                if payload.get("temperature") is not None
                else None
            ),
            max_tokens=(
                int(payload["max_tokens"])
                if payload.get("max_tokens") is not None
                else None
            ),
            trace_id=payload.get("trace_id") or request.request_id,
        )
    except ModelProviderError as exc:
        runtime.logger.warning("AI provider unavailable: %s", exc)
        return 503, {
            "error": "provider_unavailable",
            "message": str(exc),
            "models": model_router.status(),
        }
    except (ValueError, TypeError) as exc:
        return 400, {
            "error": "invalid_chat_request",
            "message": str(exc),
        }

    return 200, {
        "service": "tooru_ai",
        "chat": result,
    }


def conversations(request):
    raw_limit = request.query.get("limit", ["50"])[0]
    try:
        limit = int(raw_limit)
    except ValueError:
        return 400, {"error": "invalid_limit"}

    return 200, {
        "service": "tooru_ai",
        "conversations": memory.conversations(limit=limit),
    }


def conversation(request):
    conversation_id = str(
        request.query.get("conversation_id", [""])[0]
    ).strip()
    if not conversation_id:
        return 400, {"error": "conversation_id_required"}

    return 200, {
        "service": "tooru_ai",
        "conversation_id": conversation_id,
        "messages": memory.history(conversation_id, limit=200),
    }


def memory_remember(request):
    payload = request.json if isinstance(request.json, dict) else {}
    content = str(payload.get("content", "")).strip()
    if not content:
        return 400, {"error": "content_required"}

    try:
        item = chat_runtime.remember(
            content,
            scope=payload.get("scope"),
            source=str(payload.get("source", "web")),
            metadata=(
                payload.get("metadata")
                if isinstance(payload.get("metadata"), dict)
                else {}
            ),
        )
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_memory", "message": str(exc)}

    return 201, {
        "service": "tooru_ai",
        "memory": item,
    }


def rag_ingest(request):
    if rag is None:
        return 503, {"error": "rag_disabled"}
    payload = request.json if isinstance(request.json, dict) else {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return 400, {"error": "text_required"}
    max_chars = int(ai_cfg.get("max_document_chars", 2000000))
    if len(text) > max_chars:
        return 413, {"error": "document_too_large", "max_chars": max_chars}
    try:
        document = rag.ingest(
            text,
            title=(
                str(payload.get("title")).strip()
                if payload.get("title") is not None
                else None
            ),
            source=str(payload.get("source", "web")),
            metadata=(
                payload.get("metadata")
                if isinstance(payload.get("metadata"), dict)
                else {}
            ),
            document_id=payload.get("document_id"),
        )
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_document", "message": str(exc)}

    return 201, {
        "service": "tooru_ai",
        "document": document,
    }


def rag_search(request):
    if rag is None:
        return 503, {"error": "rag_disabled"}
    query = str(request.query.get("q", [""])[0]).strip()
    if not query:
        return 400, {"error": "query_required"}
    raw_limit = request.query.get("limit", ["6"])[0]
    try:
        limit = int(raw_limit)
    except ValueError:
        return 400, {"error": "invalid_limit"}
    return 200, {
        "service": "tooru_ai",
        "query": query,
        "chunks": rag.search(query, limit=limit),
    }


def rag_documents(request):
    if rag is None:
        return 200, {"service": "tooru_ai", "documents": []}
    raw_limit = request.query.get("limit", ["100"])[0]
    try:
        limit = int(raw_limit)
    except ValueError:
        return 400, {"error": "invalid_limit"}
    return 200, {
        "service": "tooru_ai",
        "documents": rag.documents(limit=limit),
    }


def memory_search(request):
    query = str(request.query.get("q", [""])[0]).strip()
    if not query:
        return 400, {"error": "query_required"}
    raw_limit = request.query.get("limit", ["6"])[0]
    try:
        limit = int(raw_limit)
    except ValueError:
        return 400, {"error": "invalid_limit"}

    return 200, {
        "service": "tooru_ai",
        "query": query,
        "memories": chat_runtime.search_memory(
            query,
            scope=request.query.get("scope", [None])[0],
            limit=limit,
        ),
    }


if __name__ == "__main__":
    runtime.db.initialize(runtime.version)
    runtime.run({
        "/capabilities": Route(capabilities, protected=False),
        "/runtime": Route(runtime_status, protected=False),
        "/models": Route(models, protected=False),
        "/chat": Route(chat, method="POST", protected=True),
        "/inference": Route(inference, method="POST", protected=True),
        "/conversations": Route(conversations, protected=True),
        "/conversation": Route(conversation, protected=True),
        "/memory/remember": Route(memory_remember, method="POST", protected=True),
        "/memory/search": Route(memory_search, protected=True),
        "/rag/ingest": Route(rag_ingest, method="POST", protected=True),
        "/rag/search": Route(rag_search, protected=True),
        "/rag/documents": Route(rag_documents, protected=True),
    })
