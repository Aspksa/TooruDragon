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
