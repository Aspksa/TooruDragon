from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.system import CoreRuntime, Route

CAPABILITIES = [
    "dialog",
    "memory",
    "models",
    "tools",
    "ai_orchestration",
]

runtime = CoreRuntime(
    "tooru_ai",
    "Основное AI-ядро Тору: диалог, память, модели и инструменты",
    capabilities=CAPABILITIES,
)


def capabilities(_request):
    return 200, {
        "service": "tooru_ai",
        "capabilities": CAPABILITIES,
    }


if __name__ == "__main__":
    runtime.run({
        "/capabilities": Route(capabilities, protected=False),
    })
