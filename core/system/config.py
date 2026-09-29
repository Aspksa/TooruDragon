from __future__ import annotations

import json
import os
from functools import lru_cache

from .paths import CORES_CONFIG_PATH, SYSTEM_CONFIG_PATH


def _load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def system_config() -> dict:
    config = _load_json(SYSTEM_CONFIG_PATH)
    token_env = config.get("auth", {}).get("token_env", "TOORUDRAGON_API_TOKEN")
    config.setdefault("auth", {})["token"] = os.getenv(token_env, "")
    return config


@lru_cache(maxsize=1)
def cores_config() -> dict:
    return _load_json(CORES_CONFIG_PATH)


def core_config(name: str) -> dict:
    config = cores_config()
    core = config["cores"][name]
    if isinstance(core, int):
        return {
            "port": core,
            "version": version(),
            "display_name": name,
        }
    return dict(core)


def core_address(name: str) -> tuple[str, int]:
    config = cores_config()
    core = core_config(name)
    override = os.getenv("TOORUDRAGON_PORT_OVERRIDE")
    port = int(override) if override else int(core["port"])
    return config.get("host", "127.0.0.1"), port


def core_version(name: str) -> str:
    core = core_config(name)
    return str(core.get("version", version()))


def core_display_name(name: str) -> str:
    core = core_config(name)
    return str(core.get("display_name", name))


def version() -> str:
    return str(system_config().get("version", "0.1.0-alpha"))
