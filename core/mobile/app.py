from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.common.server import run_server

HOST = "127.0.0.1"
PORT = 8705


def health():
    return 200, {
        "service": "mobile",
        "version": "0.1.0-alpha",
        "status": "ok",
        "role": "Mobile gateway and synchronization core",
    }


def info():
    return 200, {
        "service": "mobile",
        "host": HOST,
        "port": PORT,
        "purpose": [
            "mobile client gateway",
            "device synchronization",
            "session coordination",
            "push integration layer",
        ],
    }


if __name__ == "__main__":
    run_server(
        "mobile",
        HOST,
        PORT,
        {
            "/health": health,
            "/info": info,
        },
    )
