from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route

runtime = CoreRuntime(
    "laboratory",
    "Лаборатория Tooru/AI: разработка, эксперименты, тестирование и сборка",
)


def capabilities(_request):
    return 200, {
        "service": "laboratory",
        "capabilities": [
            "code",
            "experiments",
            "testing",
            "builds",
            "developer_tools",
        ],
    }


if __name__ == "__main__":
    runtime.run({
        "/capabilities": Route(capabilities, protected=False),
    })
