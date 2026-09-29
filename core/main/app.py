from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route
from core.system.compatibility import CompatibilityManager
from core.system.core_manager import CoreManager
from core.system.event_bus import EventBus
from core.system.agent_runtime import AgentRuntime, ToolRouter
from core.system.observability import Observability
from core.system.policy import PolicyEngine
from core.system.secrets import SecretStore
from core.system.supervisor import SupervisorFacade
from core.system.workflow import WorkflowEngine
from core.system.service_registry import ServiceRegistry
from core.system.watchdog import Watchdog

MAIN_CAPABILITIES = [
    "orchestration",
    "watchdog",
    "service_registry",
    "event_bus",
    "compatibility",
    "updates",
    "workflow_engine",
    "policy_engine",
    "supervisor_boundary",
]

runtime = CoreRuntime(
    "main",
    "Главное управляющее ядро TooruDragon",
    capabilities=MAIN_CAPABILITIES,
)

CORES = {
    name: f"http://{runtime.config_host}:{entry['port'] if isinstance(entry, dict) else entry}/health"
    for name, entry in runtime.cores.items()
    if name != "main"
}

event_bus = EventBus(
    max_events=int(runtime.config.get("event_fabric", {}).get("retention", 10000)),
    database=runtime.db,
)

compatibility_manager = CompatibilityManager(runtime.cores)
core_manager = CoreManager(
    host=runtime.config_host,
    cores=runtime.cores,
    root=ROOT,
)
workflow_engine = WorkflowEngine(runtime.db)
policy_engine = PolicyEngine(runtime.config.get("policy", {}))
secret_store = SecretStore()
supervisor = SupervisorFacade(architecture_version="0.3")
observability = Observability(
    max_samples=int(runtime.config.get("observability", {}).get("max_samples", 300))
)
tool_router = ToolRouter(policy_engine)
agent_runtime = AgentRuntime(workflow_engine, policy_engine, tool_router)

registry_config = runtime.config.get("service_registry", {})
service_registry = ServiceRegistry(
    stale_after_seconds=int(registry_config.get("stale_after_seconds", 35))
)
MAIN_STARTED_AT = time.monotonic()


def register_main_service() -> None:
    service_registry.register({
        "name": runtime.name,
        "display_name": runtime.display_name,
        "version": runtime.version,
        "host": runtime.host,
        "port": runtime.port,
        "role": runtime.role,
        "capabilities": runtime.capabilities,
        "pid": os.getpid(),
        "uptime_seconds": int(time.monotonic() - MAIN_STARTED_AT),
    })


def main_registry_heartbeat() -> None:
    interval = max(3, int(registry_config.get("heartbeat_seconds", 10)))
    while True:
        register_main_service()
        time.sleep(interval)


register_main_service()

watchdog_config = runtime.config.get("watchdog", {})
supervisor_config = runtime.config.get("supervisor", {})
external_supervisor_enabled = bool(supervisor_config.get("enabled", True))
watchdog = Watchdog(
    host=runtime.config_host,
    cores=runtime.cores,
    root=ROOT,
    logger=runtime.logger,
    interval_seconds=int(watchdog_config.get("interval_seconds", 10)),
    failure_threshold=int(watchdog_config.get("failure_threshold", 3)),
    auto_restart=(bool(watchdog_config.get("auto_restart", True)) and not external_supervisor_enabled),
    restart_callback=core_manager.restart,
)


def probe(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return {
                "ok": response.status == 200,
                "status_code": response.status,
                "payload": payload,
            }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)}


def cores(_request):
    states = {name: probe(url) for name, url in CORES.items()}
    all_ok = all(state.get("ok") for state in states.values())
    return (200 if all_ok else 503), {
        "service": "main",
        "version": runtime.version,
        "status": "ok" if all_ok else "degraded",
        "cores": states,
        "registry": service_registry.snapshot(),
    }


def routes(_request):
    return 200, {
        "service": "main",
        "version": runtime.version,
        "routes": {
            "/health": "Состояние главного ядра",
            "/cores": "Состояние и версии всех специализированных ядер",
            "/system": "Системная информация",
            "/events": "Последние события Event Bus",
            "/events/publish": "Публикация события",
            "/watchdog": "Состояние Watchdog",
            "/compatibility": "Проверка совместимости версий",
            "/registry": "Живой реестр сервисов",
            "/registry/register": "Регистрация и heartbeat ядра",
            "/api/cores": "Core Manager: статусы всех ядер",
            "/api/core/action": "Core Manager: start/stop/restart ядра",
            "/api/core/history": "История управляющих действий",
            "/platform": "Состояние Control Plane v0.2",
            "/api/tasks": "Список durable-задач",
            "/api/task/create": "Создать durable-задачу",
            "/api/task/claim": "Захватить задачу worker-ом",
            "/api/task/update": "Обновить состояние задачи",
            "/api/task/transitions": "История переходов задачи",
            "/events/replay": "Replay durable events",
            "/events/ack": "Подтверждение durable event offset",
            "/events/dlq": "Перенос события в dead-letter queue",
            "/observability": "Метрики и runtime telemetry",
            "/agents/plan": "Capability-gated agent plan submission",
        },
    }


def events(request):
    topic = request.query.get("topic", [None])[0]
    raw_limit = request.query.get("limit", ["50"])[0]
    try:
        limit = int(raw_limit)
    except ValueError:
        limit = 50

    return 200, {
        "service": "main",
        "events": event_bus.recent(limit=limit, topic=topic),
    }


def publish_event(request):
    payload = request.json if isinstance(request.json, dict) else {}
    topic = str(payload.get("topic", "")).strip()
    source = str(payload.get("source", "unknown")).strip() or "unknown"
    event_payload = payload.get("payload", {})

    if not topic:
        return 400, {"error": "topic_required"}
    if not isinstance(event_payload, dict):
        return 400, {"error": "payload_must_be_object"}

    event = event_bus.publish(topic, source, event_payload)
    runtime.logger.info("Event published: %s from %s", topic, source)
    return 201, {"event": event}



def event_replay(request):
    consumer = str(request.query.get("consumer", [""])[0]).strip()
    topic = request.query.get("topic", [None])[0]
    raw_limit = request.query.get("limit", ["100"])[0]
    if not consumer:
        return 400, {"error": "consumer_required"}
    try:
        items = event_bus.replay(
            consumer,
            topic=topic,
            limit=int(raw_limit),
        )
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_replay", "message": str(exc)}
    return 200, {"consumer": consumer, "events": items}


def event_ack(request):
    payload = request.json if isinstance(request.json, dict) else {}
    consumer = str(payload.get("consumer", "")).strip()
    if not consumer:
        return 400, {"error": "consumer_required"}
    try:
        event_bus.ack(consumer, int(payload.get("sequence")))
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_ack", "message": str(exc)}
    return 200, {"consumer": consumer, "acked": int(payload["sequence"])}


def event_dlq(request):
    payload = request.json if isinstance(request.json, dict) else {}
    event_id = str(payload.get("event_id", "")).strip()
    consumer = str(payload.get("consumer", "")).strip()
    error = str(payload.get("error", "processing_failed"))
    if not event_id or not consumer:
        return 400, {"error": "event_id_and_consumer_required"}
    try:
        event = event_bus.dead_letter(event_id, consumer, error)
    except KeyError:
        return 404, {"error": "event_not_found"}
    return 201, {"dead_lettered": event}


def observability_status(_request):
    return 200, {
        "service": "main",
        "observability": observability.snapshot(),
        "event_fabric": event_bus.stats(),
    }


def agent_plan(request):
    payload = request.json if isinstance(request.json, dict) else {}
    agent_id = str(payload.get("agent_id", "")).strip()
    steps = payload.get("steps", [])
    if not isinstance(steps, list):
        return 400, {"error": "steps_must_be_array"}
    try:
        plan = agent_runtime.submit_plan(
            agent_id=agent_id,
            steps=steps,
            trace_id=payload.get("trace_id"),
        )
    except (ValueError, TypeError, PermissionError) as exc:
        return 403 if isinstance(exc, PermissionError) else 400, {
            "error": "agent_plan_rejected",
            "message": str(exc),
        }
    event_bus.publish(
        "agent.plan.created",
        agent_id,
        {
            "workflow_id": plan["workflow_id"],
            "task_count": len(plan["tasks"]),
        },
        trace_id=plan["trace_id"],
    )
    return 201, {"plan": plan}


def watchdog_status(_request):
    return 200, {
        "service": "main",
        "watchdog": watchdog.snapshot(),
    }


def compatibility(_request):
    result = compatibility_manager.check()
    return (200 if result["ok"] else 409), {
        "service": "main",
        "compatibility": result,
    }


def registry_status(_request):
    return 200, {
        "service": "main",
        "registry": service_registry.snapshot(),
    }


def registry_register(request):
    payload = request.json if isinstance(request.json, dict) else {}
    name = str(payload.get("name", "")).strip()
    if name not in runtime.cores:
        return 400, {
            "error": "unknown_service",
            "message": f"Сервис {name!r} отсутствует в config/cores.json",
        }

    try:
        service = service_registry.register(payload)
    except (ValueError, TypeError) as exc:
        return 400, {
            "error": "invalid_registry_payload",
            "message": str(exc),
        }

    return 201, {
        "service": "main",
        "registered": service,
    }


def managed_cores(_request):
    return 200, {
        "service": "main",
        "manager": {
            "cores": core_manager.snapshot(),
        },
    }


def core_action(request):
    payload = request.json if isinstance(request.json, dict) else {}
    name = str(payload.get("core", "")).strip()
    action = str(payload.get("action", "")).strip().lower()

    if name not in runtime.cores:
        return 404, {
            "error": "unknown_core",
            "core": name,
        }

    actions = {
        "start": core_manager.start,
        "stop": core_manager.stop,
        "restart": core_manager.restart,
    }
    handler = actions.get(action)
    if handler is None:
        return 400, {
            "error": "unsupported_action",
            "action": action,
            "allowed": sorted(actions),
        }

    result = handler(name)
    event_bus.publish(
        "core.manager.action",
        "main",
        {
            "core": name,
            "action": action,
            "ok": bool(result.get("ok")),
            "message": result.get("message"),
        },
    )
    return (200 if result.get("ok") else 409), result


def core_history(request):
    raw_limit = request.query.get("limit", ["100"])[0]
    try:
        limit = int(raw_limit)
    except ValueError:
        limit = 100

    return 200, {
        "service": "main",
        "history": core_manager.history(limit=limit),
    }



def platform_status(_request):
    return 200, {
        "service": "main",
        "architecture": "control-plane-v0.2",
        "supervisor": supervisor.snapshot(),
        "policy": policy_engine.snapshot(),
        "secrets": secret_store.metadata(),
        "workflow": {
            "durable": True,
            "lease_based": True,
        },
        "event_fabric": event_bus.stats(),
        "external_supervisor": {
            "enabled": external_supervisor_enabled,
            "host": supervisor_config.get("host", "127.0.0.1"),
            "port": supervisor_config.get("port", 8699),
        },
    }


def tasks(request):
    state = request.query.get("state", [None])[0]
    workflow_id = request.query.get("workflow_id", [None])[0]
    raw_limit = request.query.get("limit", ["100"])[0]
    try:
        limit = int(raw_limit)
        items = workflow_engine.list_tasks(
            state=state,
            workflow_id=workflow_id,
            limit=limit,
        )
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_query", "message": str(exc)}

    return 200, {"service": "main", "tasks": items}


def task_create(request):
    payload = request.json if isinstance(request.json, dict) else {}
    try:
        task = workflow_engine.create_task(
            kind=str(payload.get("kind", "")).strip(),
            payload=payload.get("payload", {}),
            workflow_id=payload.get("workflow_id"),
            parent_id=payload.get("parent_id"),
            priority=int(payload.get("priority", 100)),
            max_attempts=int(payload.get("max_attempts", 3)),
            idempotency_key=payload.get("idempotency_key"),
            available_at=payload.get("available_at"),
            trace_id=payload.get("trace_id"),
            required_capability=payload.get("required_capability"),
        )
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_task", "message": str(exc)}

    event_bus.publish(
        "workflow.task.created",
        "main",
        {
            "task_id": task["id"],
            "workflow_id": task["workflow_id"],
            "kind": task["kind"],
            "trace_id": task["trace_id"],
        },
    )
    return 201, {"task": task}


def task_claim(request):
    payload = request.json if isinstance(request.json, dict) else {}
    worker_id = str(payload.get("worker_id", "")).strip()
    kinds = payload.get("kinds")
    if kinds is not None and not isinstance(kinds, list):
        return 400, {"error": "kinds_must_be_array"}

    try:
        task = workflow_engine.claim(
            worker_id=worker_id,
            lease_seconds=int(
                payload.get(
                    "lease_seconds",
                    runtime.config.get("workflow", {}).get("lease_seconds", 60),
                )
            ),
            kinds=kinds,
            allowed_capabilities=policy_engine.allowed_capabilities(worker_id),
        )
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_claim", "message": str(exc)}

    return 200, {"task": task}


def task_update(request):
    payload = request.json if isinstance(request.json, dict) else {}
    task_id = str(payload.get("task_id", "")).strip()
    worker_id = str(payload.get("worker_id", "")).strip()
    action = str(payload.get("action", "")).strip().lower()

    try:
        if action == "running":
            task = workflow_engine.mark_running(task_id, worker_id)
        elif action == "heartbeat":
            task = workflow_engine.heartbeat(
                task_id,
                worker_id,
                lease_seconds=int(payload.get("lease_seconds", 60)),
            )
        elif action == "complete":
            task = workflow_engine.complete(
                task_id,
                worker_id,
                result=payload.get("result", {}),
            )
        elif action == "fail":
            task = workflow_engine.fail(
                task_id,
                worker_id,
                str(payload.get("error", "task_failed")),
                retry_delay_seconds=int(payload.get("retry_delay_seconds", 5)),
            )
        elif action == "cancel":
            task = workflow_engine.cancel(
                task_id,
                reason=str(payload.get("reason", "cancelled")),
            )
        else:
            return 400, {
                "error": "unsupported_task_action",
                "allowed": ["running", "heartbeat", "complete", "fail", "cancel"],
            }
    except KeyError:
        return 404, {"error": "task_not_found", "task_id": task_id}
    except (ValueError, TypeError, RuntimeError) as exc:
        return 409, {"error": "task_transition_failed", "message": str(exc)}

    event_bus.publish(
        "workflow.task.transition",
        "main",
        {
            "task_id": task["id"],
            "workflow_id": task["workflow_id"],
            "state": task["state"],
            "trace_id": task["trace_id"],
        },
    )
    return 200, {"task": task}


def task_transitions(request):
    task_id = str(request.query.get("task_id", [""])[0]).strip()
    if not task_id:
        return 400, {"error": "task_id_required"}
    try:
        history = workflow_engine.transitions(task_id)
    except Exception as exc:
        return 500, {"error": "history_failed", "message": str(exc)}
    return 200, {"task_id": task_id, "transitions": history}


def core_alias(name: str, action: str):
    def handler(_request):
        result = getattr(core_manager, action)(name)
        event_bus.publish(
            "core.manager.action",
            "main",
            {
                "core": name,
                "action": action,
                "ok": bool(result.get("ok")),
                "message": result.get("message"),
            },
        )
        return (200 if result.get("ok") else 409), result

    return handler


if __name__ == "__main__":
    runtime.db.initialize(runtime.version)
    if bool(runtime.config.get("workflow", {}).get("requeue_expired_on_start", True)):
        recovered = workflow_engine.requeue_expired()
        if recovered:
            runtime.logger.warning("Requeued %s expired workflow tasks", recovered)

    threading.Thread(
        target=main_registry_heartbeat,
        name="registry-main",
        daemon=True,
    ).start()

    if bool(watchdog_config.get("enabled", True)):
        watchdog.start()

    event_bus.publish(
        "system.main.started",
        "main",
        {"version": runtime.version},
    )

    managed_routes = {
        "/cores": Route(cores, protected=False),
        "/routes": Route(routes, protected=False),
        "/events": Route(events, protected=False),
        "/events/publish": Route(publish_event, method="POST", protected=True),
        "/watchdog": Route(watchdog_status, protected=False),
        "/compatibility": Route(compatibility, protected=False),
        "/registry": Route(registry_status, protected=False),
        "/registry/register": Route(
            registry_register,
            method="POST",
            protected=False,
        ),
        "/api/cores": Route(managed_cores, protected=False),
        "/api/core/action": Route(core_action, method="POST", protected=True),
        "/api/core/history": Route(core_history, protected=True),
        "/platform": Route(platform_status, protected=False),
        "/api/tasks": Route(tasks, protected=True),
        "/api/task/create": Route(task_create, method="POST", protected=True),
        "/api/task/claim": Route(task_claim, method="POST", protected=True),
        "/api/task/update": Route(task_update, method="POST", protected=True),
        "/api/task/transitions": Route(task_transitions, protected=True),
        "/events/replay": Route(event_replay, protected=True),
        "/events/ack": Route(event_ack, method="POST", protected=True),
        "/events/dlq": Route(event_dlq, method="POST", protected=True),
        "/observability": Route(observability_status, protected=True),
        "/agents/plan": Route(agent_plan, method="POST", protected=True),
    }

    for core_name in runtime.cores:
        if core_name == "main":
            continue
        for action_name in ("start", "stop", "restart"):
            managed_routes[f"/api/core/{core_name}/{action_name}"] = Route(
                core_alias(core_name, action_name),
                method="POST",
                protected=True,
            )

    runtime.run(managed_routes)
