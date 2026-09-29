from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route

runtime = CoreRuntime(
    "main",
    "Главное управляющее ядро TooruDragon",
)

CORES = {
    name: f"http://{runtime.config_host}:{port}/health"
    for name, port in runtime.cores.items()
    if name != "main"
}


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
        "status": "ok" if all_ok else "degraded",
        "cores": states,
    }


def routes(_request):
    return 200, {
        "service": "main",
        "routes": {
            "/health": "Состояние главного ядра",
            "/cores": "Состояние всех специализированных ядер",
            "/system": "Системная информация",
        },
    }


if __name__ == "__main__":
    runtime.run({
        "/cores": Route(cores, protected=False),
        "/routes": Route(routes, protected=False),
    })
