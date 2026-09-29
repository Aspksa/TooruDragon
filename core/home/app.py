from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route

runtime = CoreRuntime(
    "home",
    "Домашнее ядро: бытовые сценарии, автоматизация и персональные задачи",
)


def capabilities(_request):
    return 200, {
        "service": "home",
        "capabilities": [
            "home_automation",
            "personal_tasks",
            "local_devices",
        ],
    }


if __name__ == "__main__":
    runtime.run({
        "/capabilities": Route(capabilities, protected=False),
    })
