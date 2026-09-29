# TooruDragon Core Platform v0.2

Core Platform v0.2 introduces stable boundaries for long-lived evolution without
requiring the current Python implementation to be rewritten.

## Control Plane

The current process model remains compatible, but Main Core now exposes a stable
control-plane boundary:

- `SupervisorFacade` — embedded Supervisor contract for the current implementation;
- `CoreManager` — lifecycle management;
- `PolicyEngine` — deny-by-default capabilities;
- `SecretStore` — pluggable secret providers;
- `WorkflowEngine` — durable task execution.

The embedded Supervisor is intentionally an abstraction, not a claim that an
external daemon already exists. A future Rust service can implement the same
boundary while Main Core keeps the same public contract.

## Contracts

Language-neutral schemas live in `contracts/`:

- `envelope.v1.schema.json`
- `task.v1.schema.json`

Python code uses `core/system/contracts.py`.

Every cross-component envelope carries:

- protocol;
- contract version;
- globally unique message id;
- source/target;
- timestamp;
- trace id;
- payload.

This is the compatibility boundary for future Rust, Go, TypeScript, Mojo or
remote-node implementations.

## Durable Workflow Engine

SQLite is used as the local persistence backend, but the API is deliberately
backend-independent.

Task lifecycle:

```text
created
  ↓
queued
  ↓
claimed
  ↓
running
  ├── completed
  ├── retrying → claimed
  ├── failed
  └── cancelled
```

A claim has a lease. If a worker crashes and its lease expires, the task can be
returned to `retrying` instead of being lost forever.

Supported reliability features:

- idempotency keys;
- workflow and parent ids;
- priorities;
- retry budgets;
- delayed availability;
- leases and heartbeats;
- transition history;
- trace ids;
- capability requirements;
- recovery of expired leases.

## Workflow API

### List tasks

```http
GET /api/tasks
GET /api/tasks?state=retrying
GET /api/tasks?workflow_id=<id>
```

### Create

```http
POST /api/task/create
Content-Type: application/json

{
  "kind": "work.document.index",
  "payload": {"document_id": "42"},
  "priority": 50,
  "max_attempts": 3,
  "idempotency_key": "index-document-42",
  "required_capability": "documents.index"
}
```

### Claim

```http
POST /api/task/claim

{
  "worker_id": "work",
  "kinds": ["work.document.index"]
}
```

The worker can only claim tasks whose `required_capability` is permitted by the
Policy Engine. Tasks without a required capability remain claimable.

### State updates

```http
POST /api/task/update
```

Actions:

- `running`
- `heartbeat`
- `complete`
- `fail`
- `cancel`

### Transition audit

```http
GET /api/task/transitions?task_id=<id>
```

## Policy Engine

Policies are configured in `config/system.json`.

The default is deny. A short list is treated as an allow list:

```json
{
  "_default": "deny",
  "work": [
    "workflow.worker",
    "documents.index"
  ]
}
```

Explicit allow/deny dictionaries are also supported.

## Secrets

`SecretStore` never writes secret values to SQLite or JSON.

The environment provider reads environment variables using:

```text
TOORUDRAGON_SECRET_<NORMALIZED_NAME>
```

Example:

```text
openai.api_key
→ TOORUDRAGON_SECRET_OPENAI_API_KEY
```

The provider interface is intentionally replaceable by Windows Credential
Manager, DPAPI or an external vault later.

## Platform status

```http
GET /platform
```

Returns non-secret metadata about:

- Supervisor boundary;
- policy engine;
- secret providers;
- workflow durability.

## Update quality gate

Safe Update now runs:

1. Python compilation;
2. platform unit tests;
3. normal rolling apply;
4. runtime health validation;
5. rollback on failure.

Tests cover contracts, default-deny policy, idempotency, capability-filtered
claims and retry exhaustion.

## Next architecture milestone

The next major step should be an external Supervisor process plus durable Event
Fabric. The Python `SupervisorFacade` is the compatibility seam for that
migration.
