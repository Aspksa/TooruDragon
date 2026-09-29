from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.common.server import run_server

HOST = "127.0.0.1"
PORT = 8703


def health():
    return 200, {
        "service": "home",
        "version": "0.1.0-alpha",
        "status": "ok",
        "role": "Home automation and personal scenarios",
    }


if __name__ == "__main__":
    run_server("home", HOST, PORT, {"/health": health})
