from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route

CAPABILITIES = [
    "projects",
    "documents",
    "tasks",
    "work_integrations",
]

runtime = CoreRuntime(
    "work",
    "Рабочее ядро: проекты, документы, задачи и рабочие интеграции",
    capabilities=CAPABILITIES,
)


def capabilities(_request):
    return 200, {
        "service": "work",
        "capabilities": CAPABILITIES,
    }


if __name__ == "__main__":
    runtime.run({
        "/capabilities": Route(capabilities, protected=False),
    })
