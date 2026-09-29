from __future__ import annotations

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.system.updater import UpdateManager


if __name__ == "__main__":
    result = UpdateManager().update()
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.ok else 1)
