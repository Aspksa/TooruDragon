from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .logging import get_logger
from .paths import ROOT

logger = get_logger("backup")


class BackupManager:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.backups_dir = root / "backups"
        self.data_dir = root / "data"
        self.config_dir = root / "config"

    def _git_head(self) -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def _backup_database(self, destination: Path) -> None:
        source = self.data_dir / "toorudragon.db"
        if not source.exists():
            return

        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source, timeout=10) as src:
            with sqlite3.connect(destination, timeout=10) as dst:
                src.backup(dst)

    def create(self, reason: str = "manual") -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        target = self.backups_dir / stamp
        target.mkdir(parents=True, exist_ok=False)

        config_target = target / "config"
        config_target.mkdir(parents=True, exist_ok=True)
        if self.config_dir.exists():
            for item in self.config_dir.iterdir():
                if item.is_file():
                    shutil.copy2(item, config_target / item.name)

        self._backup_database(target / "data" / "toorudragon.db")

        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "git_head": self._git_head(),
        }
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info("Backup created: %s", target)
        return target

    def restore(self, backup_path: Path, restore_git: bool = True) -> bool:
        backup_path = Path(backup_path)
        manifest_path = backup_path / "manifest.json"
        if not manifest_path.exists():
            logger.error("Backup manifest not found: %s", backup_path)
            return False

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        if restore_git:
            git_head = str(manifest.get("git_head", "")).strip()
            if git_head:
                result = subprocess.run(
                    ["git", "reset", "--hard", git_head],
                    cwd=self.root,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if result.returncode != 0:
                    logger.error("Git rollback failed: %s", result.stderr.strip())
                    return False

        config_source = backup_path / "config"
        if config_source.exists():
            self.config_dir.mkdir(parents=True, exist_ok=True)
            for item in config_source.iterdir():
                if item.is_file():
                    shutil.copy2(item, self.config_dir / item.name)

        db_source = backup_path / "data" / "toorudragon.db"
        if db_source.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db_source, self.data_dir / "toorudragon.db")

        logger.warning("Backup restored: %s", backup_path)
        return True

    def latest(self) -> Path | None:
        if not self.backups_dir.exists():
            return None
        backups = sorted(path for path in self.backups_dir.iterdir() if path.is_dir())
        return backups[-1] if backups else None

    def prune(self, keep: int = 10) -> None:
        if keep < 1 or not self.backups_dir.exists():
            return
        backups = sorted(path for path in self.backups_dir.iterdir() if path.is_dir())
        for path in backups[:-keep]:
            shutil.rmtree(path, ignore_errors=True)
