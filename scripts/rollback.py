from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.system.backup import BackupManager


if __name__ == "__main__":
    manager = BackupManager()
    backup = Path(sys.argv[1]) if len(sys.argv) > 1 else manager.latest()
    if backup is None:
        print("[ROLLBACK] Резервные копии не найдены.")
        raise SystemExit(1)

    print(f"[ROLLBACK] Восстанавливаю: {backup}")
    raise SystemExit(0 if manager.restore(backup, restore_git=True) else 1)
