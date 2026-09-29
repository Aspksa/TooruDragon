from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route
from core.system.compatibility import CompatibilityManager
from core.system.event_bus import EventBus
from core.system.watchdog import Watchdog

runtime = CoreRuntime(
    "main",
    "Главное управляющее ядро TooruDragon",
)

CORES = {
    name: f"http://{runtime.config_host}:{entry['port'] if isinstance(entry, dict) else entry}/health"
    for name, entry in runtime.cores.items()
    if name != "main"
}

event_bus = EventBus(
    max_events=int(runtime.config.get("event_bus", {}).get("max_events", 500))
)

compatibility_manager = CompatibilityManager(runtime.cores)

watchdog_config = runtime.config.get("watchdog", {})
watchdog = Watchdog(
    host=runtime.config_host,
    cores=runtime.cores,
    root=ROOT,
    logger=runtime.logger,
    interval_seconds=int(watchdog_config.get("interval_seconds", 10)),
    failure_threshold=int(watchdog_config.get("failure_threshold", 3)),
    auto_restart=bool(watchdog_config.get("auto_restart", True)),
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


if __name__ == "__main__":
    if bool(watchdog_config.get("enabled", True)):
        watchdog.start()

    event_bus.publish(
        "system.main.started",
        "main",
        {"version": runtime.version},
    )

    runtime.run({
        "/cores": Route(cores, protected=False),
        "/routes": Route(routes, protected=False),
        "/events": Route(events, protected=False),
        "/events/publish": Route(publish_event, method="POST", protected=True),
        "/watchdog": Route(watchdog_status, protected=False),
        "/compatibility": Route(compatibility, protected=False),
    })
