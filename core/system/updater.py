from __future__ import annotations

import subprocess

from .logging import get_logger
from .paths import ROOT


logger = get_logger("updater")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args),
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def update(branch: str = "main") -> bool:
    logger.info("Checking GitHub updates for branch %s", branch)

    fetch = _run("git", "fetch", "origin", branch)
    if fetch.returncode != 0:
        logger.warning("git fetch failed: %s", fetch.stderr.strip())
        return False

    pull = _run("git", "pull", "--ff-only", "origin", branch)
    if pull.returncode != 0:
        logger.warning("git pull failed: %s", pull.stderr.strip())
        return False

    logger.info("Repository update completed")
    return True
