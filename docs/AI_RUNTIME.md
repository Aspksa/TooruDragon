# TooruDragon AI Runtime v0.3.0

Tooru/AI now has a real provider-independent chat runtime.

## Architecture

```text
Web Agent Console
      |
      v
Gateway :8698
      |
      v
Tooru/AI :8701
      |
      +-- ChatRuntime
      +-- ModelRouter
      +-- AIMemoryStore
      +-- RAGIndex
      +-- SecretStore
```

The runtime does not fabricate responses when no model provider is available.
`POST /chat` returns `503 provider_unavailable` until an enabled provider is
configured.

## Model Router

Providers are configured in `config/system.json` under
`ai_runtime.model_router.providers`.

Only provider names already present in configuration can be selected by API
clients. A chat request cannot supply an arbitrary base URL.

Current provider type:

- `openai_compatible`

This allows local or remote servers exposing a compatible
`/chat/completions` endpoint.

### Local provider

The repository includes a disabled local provider template:

```json
{
  "local": {
    "type": "openai_compatible",
    "enabled": false,
    "base_url": "http://127.0.0.1:11434/v1",
    "model": "",
    "timeout_seconds": 90,
    "temperature": 0.3,
    "max_tokens": 2048
  }
}
```

To use it:

1. run an OpenAI-compatible model server locally;
2. set its actual `base_url`;
3. set an actual model identifier;
4. change `enabled` to `true`.

No local model is assumed to be installed by TooruDragon.

### Remote provider

A remote OpenAI-compatible provider template is also present and disabled.

The API key must not be written to `config/system.json`.

For the configured secret name:

```text
openai.api_key
```

the environment variable is:

```text
TOORUDRAGON_SECRET_OPENAI_API_KEY
```

`SecretStore` resolves the value at runtime.

## Chat API

```http
POST /chat
```

Example body:

```json
{
  "message": "Explain the current system health",
  "conversation_id": null,
  "provider": "local",
  "model": null
}
```

The response contains:

- conversation id;
- trace id;
- selected provider/model;
- assistant content;
- provider usage metadata when available;
- retrieved memory items;
- retrieved RAG chunks.

Successful user/assistant exchanges are persisted in one SQLite transaction.
Provider failure does not create a fake assistant message or an empty
conversation.

## Conversation memory

Tables:

- `ai_conversations`
- `ai_messages`
- `ai_memory_items`

Endpoints:

```text
GET  /conversations
GET  /conversation?conversation_id=<id>
POST /memory/remember
GET  /memory/search?q=<query>
```

Conversation history is automatically passed to the model up to the configured
history limit.

Explicit retrieval memory is separate from ordinary conversation history.
This avoids silently treating every message as durable semantic memory.

## RAG

RAG endpoints:

```text
POST /rag/ingest
GET  /rag/search?q=<query>
GET  /rag/documents
```

Ingestion performs deterministic local chunking and stores:

- `ai_documents`
- `ai_document_chunks`

Current retrieval is lexical token-overlap scoring. It is intentionally a
backend boundary, not presented as vector search.

The Chat Runtime injects relevant chunks as supporting system context with an
explicit instruction that retrieved text is context and cannot override system
or user instructions.

Future backends can replace lexical retrieval with embeddings / pgvector
without changing the public chat contract.

## Chat context order

The request sent to the selected provider is assembled as:

```text
System prompt
    ↓
Relevant explicit memory
    ↓
Relevant RAG document chunks
    ↓
Recent conversation history
    ↓
Current user message
```

Retrieved content is labelled as untrusted supporting context.

## Runtime status

```text
GET /runtime
GET /models
```

Status reports configured providers, whether they are enabled, whether required
secrets are available, and the active memory/RAG backends.

Secret values are never returned.

## Web Control Center

The Agent Console calls Tooru/AI through the local Gateway:

```text
Browser :8710
  → Web proxy
  → Gateway :8698
  → Tooru/AI active slot
```

This means the AI chat path follows Blue/Green routing during Tooru/AI
deployments.

The Web UI supports:

- provider selection;
- optional model override;
- conversation selection/history;
- chat;
- explicit memory save/search;
- RAG document text ingestion;
- RAG search;
- Tool Router operations;
- Planner → Workflow operations.
