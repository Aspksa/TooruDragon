from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route

runtime = CoreRuntime(
    "mobile",
    "Мобильное ядро: шлюз, синхронизация устройств и мобильные сессии",
)


def info(_request):
    return 200, {
        "service": "mobile",
        "host": runtime.host,
        "port": runtime.port,
        "purpose": [
            "mobile_client_gateway",
            "device_synchronization",
            "session_coordination",
            "push_integration",
        ],
    }


if __name__ == "__main__":
    runtime.run({
        "/info": Route(info, protected=False),
    })
