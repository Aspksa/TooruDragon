from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import system_config
from .paths import ROOT


def get_logger(name: str) -> logging.Logger:
    config = system_config().get("logging", {})
    log_dir = ROOT / config.get("directory", "logs")
    max_bytes = int(config.get("rotation_bytes", 2_000_000))
    backup_count = int(config.get("backup_count", 5))

    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"toorudragon.{name}")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        log_dir / f"{name}.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger
