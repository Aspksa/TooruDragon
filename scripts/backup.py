from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.system.backup import BackupManager


if __name__ == "__main__":
    manager = BackupManager()
    path = manager.create(reason="manual")
    manager.prune(keep=10)
    print(f"[BACKUP] Готово: {path}")
