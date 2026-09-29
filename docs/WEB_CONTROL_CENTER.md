# TooruDragon Web Control Center v0.3.0

Web Control Center runs locally at:

```text
http://127.0.0.1:8710
```

It is a zero-build, offline-first control surface for TooruDragon.

## Architecture

The browser does not call Main Core, Supervisor or Gateway directly.

```text
Browser :8710
    |
    v
Web Control Proxy
    |
    +-- Main Core :8700
    +-- Supervisor :8699
    +-- Gateway :8698
```

The proxy uses a strict upstream and route allowlist. It does not provide a
generic localhost proxy.

If `TOORUDRAGON_API_TOKEN` is set, the Web server injects the Bearer token
server-side. The token is never embedded in HTML or JavaScript.

Control POST requests additionally require:

- same-origin browser origin;
- `application/json`;
- an explicitly allowlisted upstream route.

This reduces browser-CSRF risk while preserving the local-only deployment model.

## Pages

### Overview

Shows:

- total system health;
- online cores;
- Main Core resident memory;
- durable event count;
- Supervisor uptime;
- active Blue/Green deployments;
- live core cards.

### Cores

Lifecycle operations are sent through External Supervisor:

- Start;
- Restart;
- Stop;
- Safe Mode enable/disable.

### Tasks

Durable Workflow Engine view:

- latest tasks;
- state;
- priority;
- attempts;
- workflow id;
- task creation form;
- capability requirement;
- idempotency key;
- JSON payload.

### Events

Displays recent Durable Event Fabric events with:

- sequence;
- topic;
- source;
- timestamp;
- payload.

### Agent

Agent Runtime surface:

- agent id;
- permitted Tool Router catalog;
- policy-gated tool invocation;
- bounded plan submission;
- resulting workflow JSON.

### Control Plane

Shows:

- External Supervisor snapshot;
- Gateway routes;
- active Blue/Green deployments;
- Event Fabric consumer diagnostics;
- deployment complete/rollback actions.

## Web health

Rolling Update can validate the Web process through:

```http
GET /health
```

Response:

```json
{
  "service": "web",
  "version": "0.3.0",
  "status": "ok",
  "control_center": true
}
```

## Static assets

The interface has no CDN or build-tool dependency:

```text
web/
├── index.html
├── styles.css
├── app.js
├── server.py
└── start.bat
```

This keeps the portable Windows distribution self-contained.

## Security

The Web server:

- binds only to `127.0.0.1`;
- sets CSP, no-sniff and no-referrer headers;
- blocks directory traversal;
- uses an explicit API proxy allowlist;
- keeps Bearer credentials server-side;
- blocks untrusted browser origins for POST control operations;
- requires JSON for control POSTs.

It intentionally does not expose shell execution, arbitrary filesystem access,
arbitrary HTTP proxying or secret values.


## Web Control Center 2.0

The v0.3.0 Control Center now includes a second operational layer focused on
live diagnostics and execution visibility.

### Live SSE events

The browser opens:

```text
GET /stream/events
```

The Web server reads incremental durable events from Main Core and emits
Server-Sent Events. Browser reconnects resume from `Last-Event-ID`, so the
stream does not intentionally restart from the beginning.

The SSE endpoint remains same-origin and the browser still never receives the
system Bearer token.

### Telemetry charts

The Overview renders zero-dependency canvas charts for:

- Main Core resident memory;
- Main Core CPU usage derived from process CPU-time deltas;
- average core health-check latency.

Observability samples now include Unix timestamps. On Windows, process CPU time
uses `GetProcessTimes` instead of the previous zero-value fallback.

### Workflow Graph

The Workflow page loads durable tasks, groups them by `workflow_id`, calculates
parent depth from `parent_id` and renders an SVG dependency graph.

Selecting a graph node retrieves:

```text
GET /api/task/transitions?task_id=<id>
```

and displays the durable transition audit for that task.

### Agent Console

The Agent page now maintains an execution transcript for real platform
operations:

- Tool Router calls;
- Planner submissions;
- workflow and trace identifiers;
- errors.

This is deliberately not presented as an LLM chat. The current Tooru/AI core has
no inference/chat endpoint yet. When a model runtime is added, it can be attached
to this console without faking responses in the current release.

### Audit

The Audit page aggregates:

- Core Manager lifecycle history;
- recent Durable Event Fabric activity;
- DLQ count;
- Event Fabric consumer lag;
- retention-gap state.

This provides a single operator view for lifecycle and event-delivery integrity.

## Zero-build principle

Web Control Center 2.0 still has no npm, bundler, framework or CDN dependency.
Charts, workflow visualization and streaming are implemented with browser-native
Canvas, SVG and EventSource APIs.


## Real Tooru/AI Chat

Agent Console now talks to the actual Tooru/AI Chat Runtime through Gateway
routing.

It exposes:

- configured provider status;
- provider selection;
- optional model override;
- persisted conversations;
- real `POST /chat`;
- explicit memory save/search;
- RAG document ingestion/search.

If no provider is enabled, the console displays the actual
`provider_unavailable` response. It does not synthesize a fake answer.

See `docs/AI_RUNTIME.md`.
