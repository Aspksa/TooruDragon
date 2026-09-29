from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.system.config import version
from core.system.database import Database


def main() -> int:
    db = Database()
    db.initialize(version())
    print(f"[DB] Ready: {db.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
