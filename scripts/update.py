from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.system.updater import UpdateManager


def run_rolling_update(previous_head: str, current_head: str) -> int:
    script = ROOT / "scripts" / "rolling_update.ps1"

    if os.name != "nt":
        print("[UPDATE] Код обновлён. Rolling restart автоматически поддерживается на Windows.")
        return 0

    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Python",
        sys.executable,
        "-PreviousHead",
        previous_head,
        "-CurrentHead",
        current_head,
    ]
    return subprocess.call(command, cwd=ROOT)


def main() -> int:
    result = UpdateManager().update()
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))

    if not result.ok:
        return 1

    if not result.changed:
        return 0

    if not result.previous_head or not result.current_head:
        print("[UPDATE] Не удалось определить диапазон обновления.")
        return 2

    rolling_code = run_rolling_update(
        result.previous_head,
        result.current_head,
    )

    if rolling_code == 0:
        print("[UPDATE] Новая версия применена к работающей системе.")
        return 0

    if rolling_code == 40:
        print("[UPDATE] Новая версия не прошла проверку. Старая версия восстановлена и работает.")
        return 3

    print(f"[UPDATE] Rolling update завершился с кодом {rolling_code}.")
    return rolling_code or 4


if __name__ == "__main__":
    raise SystemExit(main())
