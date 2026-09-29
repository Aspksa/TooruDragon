from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.common.server import run_server

HOST = "127.0.0.1"
PORT = 8702


def health():
    return 200, {
        "service": "workshop",
        "version": "0.1.0-alpha",
        "status": "ok",
        "role": "Development and build workshop",
    }


if __name__ == "__main__":
    run_server("workshop", HOST, PORT, {"/health": health})
