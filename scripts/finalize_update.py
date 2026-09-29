from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.system.updater import UpdateManager


def main() -> int:
    manager = UpdateManager()

    if "--success" in sys.argv:
        manager.clear_pending()
        print("[UPDATE] Финальный health-check пройден. Обновление подтверждено.")
        return 0

    if "--rollback" in sys.argv:
        if not manager.pending_path.exists():
            print("[UPDATE] Pending update отсутствует — rollback не требуется.")
            return 0

        ok = manager.rollback_pending()
        print(
            "[UPDATE] Rollback после неудачного health-check выполнен."
            if ok
            else "[UPDATE] Не удалось выполнить rollback."
        )
        return 0 if ok else 1

    print("[UPDATE] Используйте --success или --rollback.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
