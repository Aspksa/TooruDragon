from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .backup import BackupManager
from .logging import get_logger
from .paths import ROOT

logger = get_logger("updater")


@dataclass
class UpdateResult:
    ok: bool
    changed: bool = False
    rolled_back: bool = False
    backup_path: str | None = None
    previous_head: str | None = None
    current_head: str | None = None
    message: str = ""


class UpdateManager:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.backups = BackupManager(root)
        self.runtime_dir = root / "runtime"
        self.pending_path = self.runtime_dir / "pending_update.json"

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            list(args),
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )

    def _head(self) -> str:
        result = self._run("git", "rev-parse", "HEAD")
        return result.stdout.strip() if result.returncode == 0 else ""

    def _is_clean(self) -> bool:
        result = self._run("git", "status", "--porcelain")
        return result.returncode == 0 and not result.stdout.strip()

    def _python_validation(self) -> bool:
        python = sys.executable

        compile_result = subprocess.run(
            [
                python,
                "-m",
                "compileall",
                "-q",
                "core",
                "scripts",
                "web",
            ],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )
        if compile_result.returncode != 0:
            logger.error("Python validation failed: %s", compile_result.stderr.strip())
            return False

        init_result = subprocess.run(
            [python, "scripts/init_db.py"],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )
        if init_result.returncode != 0:
            logger.error("Database migration/init failed: %s", init_result.stderr.strip())
            return False

        return True

    def _write_pending(
        self,
        backup: Path,
        previous_head: str,
        current_head: str,
    ) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.pending_path.write_text(
            json.dumps(
                {
                    "backup_path": str(backup),
                    "previous_head": previous_head,
                    "current_head": current_head,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def clear_pending(self) -> None:
        self.pending_path.unlink(missing_ok=True)

    def rollback_pending(self) -> bool:
        if not self.pending_path.exists():
            return False

        payload = json.loads(self.pending_path.read_text(encoding="utf-8"))
        backup = Path(payload["backup_path"])
        restored = self.backups.restore(backup, restore_git=True)
        if restored:
            self.clear_pending()
        return restored

    def update(self, branch: str = "main", remote: str = "origin") -> UpdateResult:
        logger.info("Safe update started: %s/%s", remote, branch)

        if not self._is_clean():
            return UpdateResult(
                ok=False,
                message="Рабочая копия Git содержит незакоммиченные изменения. "
                "Автообновление остановлено, чтобы ничего не потерять.",
            )

        previous_head = self._head()

        fetch = self._run("git", "fetch", remote, branch)
        if fetch.returncode != 0:
            return UpdateResult(
                ok=False,
                previous_head=previous_head,
                message=f"git fetch завершился ошибкой: {fetch.stderr.strip()}",
            )

        remote_head_result = self._run("git", "rev-parse", f"{remote}/{branch}")
        remote_head = remote_head_result.stdout.strip()
        if remote_head == previous_head:
            return UpdateResult(
                ok=True,
                changed=False,
                previous_head=previous_head,
                current_head=previous_head,
                message="Обновлений нет.",
            )

        backup = self.backups.create(reason=f"before-update:{previous_head}")
        self.backups.prune(keep=10)

        pull = self._run("git", "pull", "--ff-only", remote, branch)
        if pull.returncode != 0:
            restored = self.backups.restore(backup, restore_git=True)
            return UpdateResult(
                ok=False,
                changed=False,
                rolled_back=restored,
                backup_path=str(backup),
                previous_head=previous_head,
                current_head=self._head(),
                message="git pull завершился ошибкой. "
                + ("Выполнен rollback." if restored else "Rollback не выполнен."),
            )

        current_head = self._head()
        if not self._python_validation():
            restored = self.backups.restore(backup, restore_git=True)
            return UpdateResult(
                ok=False,
                changed=True,
                rolled_back=restored,
                backup_path=str(backup),
                previous_head=previous_head,
                current_head=self._head(),
                message="Проверка новой версии не пройдена. "
                + ("Выполнен rollback." if restored else "Rollback завершился ошибкой."),
            )

        self._write_pending(backup, previous_head, current_head)
        logger.info("Safe update completed: %s -> %s", previous_head, current_head)
        return UpdateResult(
            ok=True,
            changed=True,
            rolled_back=False,
            backup_path=str(backup),
            previous_head=previous_head,
            current_head=current_head,
            message="Обновление установлено. Ожидается финальный health-check после запуска.",
        )


def update(branch: str = "main") -> bool:
    return UpdateManager().update(branch=branch).ok
