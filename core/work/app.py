from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route

runtime = CoreRuntime(
    "work",
    "Рабочее ядро: проекты, документы, задачи и рабочие интеграции",
)


def capabilities(_request):
    return 200, {
        "service": "work",
        "capabilities": [
            "projects",
            "documents",
            "tasks",
            "work_integrations",
        ],
    }


if __name__ == "__main__":
    runtime.run({
        "/capabilities": Route(capabilities, protected=False),
    })
