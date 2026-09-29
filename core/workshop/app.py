from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route

CAPABILITIES = [
    "code",
    "experiments",
    "testing",
    "builds",
    "developer_tools",
]

runtime = CoreRuntime(
    "laboratory",
    "Лаборатория Tooru/AI: разработка, эксперименты, тестирование и сборка",
    capabilities=CAPABILITIES,
)


def capabilities(_request):
    return 200, {
        "service": "laboratory",
        "capabilities": CAPABILITIES,
    }


if __name__ == "__main__":
    runtime.run({
        "/capabilities": Route(capabilities, protected=False),
    })
