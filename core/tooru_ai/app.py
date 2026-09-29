from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route

runtime = CoreRuntime(
    "tooru_ai",
    "Основное AI-ядро Тору: диалог, память, модели и инструменты",
)


def capabilities(_request):
    return 200, {
        "service": "tooru_ai",
        "capabilities": [
            "dialog",
            "memory",
            "models",
            "tools",
            "ai_orchestration",
        ],
    }


if __name__ == "__main__":
    runtime.run({
        "/capabilities": Route(capabilities, protected=False),
    })
