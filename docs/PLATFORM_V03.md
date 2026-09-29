# TooruDragon Core Platform v0.3 Alpha

v0.3 moves TooruDragon from an in-process orchestration model toward a real
Control Plane / Intelligence Plane split while preserving the current Alpha
cores and local-first deployment model.

## Architecture

```text
Windows Launcher / CLI
        |
        v
External Supervisor :8699
        |
        +-- desired state
        +-- recovery
        +-- crash-loop protection
        +-- safe mode
        +-- Main Core lifecycle
        |
        v
Main Core :8700
        |
        +-- Core Manager
        +-- Durable Event Fabric
        +-- Workflow Engine
        +-- Policy Engine
        +-- Agent Runtime
        +-- Tool Router
        +-- Observability
        |
        +---- Tooru/AI
        +---- Laboratory
        +---- Home
        +---- Work
        +---- Mobile
```

## External Supervisor

The Supervisor is a separate Python process at `127.0.0.1:8699`.
It is deliberately independent of Main Core and therefore can recover Main
after a crash.

Endpoints:

- `GET /health`
- `GET /status`
- `POST /core/action`
- `POST /safe-mode/enable`
- `POST /safe-mode/disable`

When system Bearer authentication is enabled, Supervisor POST endpoints require
the same token.

Supervisor recovery includes:

- persisted desired state (`running` / `stopped`);
- startup grace to avoid cold-start races;
- failure threshold;
- restart budget;
- crash-loop detection;
- automatic Safe Mode.

Intentional stops are not treated as failures.

## Health model

Every core now exposes:

- `/live` — process liveness;
- `/ready` — readiness including database access;
- `/health` — backward-compatible service health.

This separates "the process exists" from "the service is ready to receive work".

## Durable Event Fabric

The old Event Bus API remains backward compatible, but persistence now uses
SQLite tables:

- `durable_events`;
- `event_offsets`;
- `event_dead_letters`.

Features:

- monotonic sequence;
- trace id;
- replay;
- consumer offsets;
- ack;
- dead-letter queue;
- retention.

Main Core APIs:

- `GET /events`
- `POST /events/publish`
- `GET /events/replay?consumer=...`
- `POST /events/ack`
- `POST /events/dlq`

## Workflow Engine

Tasks remain durable and lease-based. v0.3 additionally enforces dependency
ordering:

```text
parent queued
  -> parent claimed
  -> parent running
  -> parent completed
  -> child becomes claimable
```

If a parent reaches terminal `failed` or `cancelled`, non-terminal descendants
are cancelled with an explicit dependency reason instead of remaining queued
forever.

## Agent Runtime

The Agent Runtime is capability-gated and intentionally does not grant shell,
filesystem or secret access by default.

Components:

- `Planner` — validates and bounds a proposed plan;
- `AgentRuntime` — turns validated steps into durable workflow tasks;
- `ToolRouter` — capability-gated tool invocation;
- `PolicyEngine` — default-deny authorization.

Current safe built-in tools:

- `system.cores.snapshot`
- `events.stats`

Tooru/AI receives only the `system.observe` capability for these read-only
tools.

APIs:

- `POST /agents/plan`
- `GET /agents/tools?agent_id=...`
- `POST /agents/tool/invoke`

The current Planner is a deterministic validation/budget layer. It is not
presented as an LLM planner. Model-driven planning can be attached later behind
the same contract.

## Observability

Main Core exposes `GET /observability`.

Current telemetry includes:

- PID;
- uptime;
- resident memory;
- process CPU time where the platform exposes it;
- counters;
- recent samples;
- Event Fabric statistics.

HTTP responses also expose `X-Request-Id`, and request payloads receive the same
correlation identifier.

## Blue/Green foundation

`DeploymentCoordinator` can launch a candidate copy of a core on an isolated
temporary port using `TOORUDRAGON_PORT_OVERRIDE`.

Candidate instances are explicitly prevented from registering themselves as the
live production service.

Implemented:

- candidate staging;
- isolated port override;
- candidate health probing;
- registry isolation.

Not yet claimed as complete zero-downtime deployment:

- no production traffic router/switch exists yet;
- promotion and draining are not faked.

The next step for true Blue/Green is a stable local gateway that owns canonical
ports while core instances bind internal dynamic ports.

## Launcher integration

The Windows Launcher now:

- uses Supervisor for lifecycle operations;
- persists desired state before Stop All;
- stops Web UI, cores and Supervisor on Stop All;
- restores desired state on Start All;
- shows Supervisor as a diagnostic;
- reports platform version `0.3.0-alpha`.

## Quality gates

Safe Update and GitHub Actions compile:

- `core`;
- `scripts`;
- `web`;
- `tests`;
- `supervisor`.

Unit tests cover:

- contracts;
- policy;
- workflow idempotency;
- capability-filtered claims;
- retry exhaustion;
- dependency gating;
- dependency failure cascade;
- durable event replay/ack/DLQ;
- policy-gated agent planning.

## Future boundary

The external Supervisor is currently Python so the architecture can stabilize
before a language migration. The contract is intentionally narrow enough to
replace it later with a Rust Windows Service/Linux daemon without coupling the
rest of TooruDragon to that implementation.
