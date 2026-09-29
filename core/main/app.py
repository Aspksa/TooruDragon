from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.common.server import run_server

HOST = "127.0.0.1"
PORT = 8700

CORES = {
    "tooru_ai": "http://127.0.0.1:8701/health",
    "laboratory": "http://127.0.0.1:8702/health",
    "home": "http://127.0.0.1:8703/health",
    "work": "http://127.0.0.1:8704/health",
    "mobile": "http://127.0.0.1:8705/health",
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
        return {
            "ok": False,
            "error": str(exc),
        }


def health():
    return 200, {
        "service": "main",
        "version": "0.1.0-alpha",
        "status": "ok",
    }


def cores():
    states = {name: probe(url) for name, url in CORES.items()}
    all_ok = all(state.get("ok") for state in states.values())
    return (200 if all_ok else 503), {
        "service": "main",
        "status": "ok" if all_ok else "degraded",
        "cores": states,
    }


def routes():
    return 200, {
        "service": "main",
        "routes": {
            "/health": "Main Core health",
            "/cores": "Health status of all specialized cores",
        },
    }


if __name__ == "__main__":
    run_server(
        "main",
        HOST,
        PORT,
        {
            "/health": health,
            "/cores": cores,
            "/routes": routes,
        },
    )
