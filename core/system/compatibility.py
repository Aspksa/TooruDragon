from __future__ import annotations

import json

from .paths import CONFIG_DIR


COMPATIBILITY_PATH = CONFIG_DIR / "compatibility.json"


def _version_tuple(value: str) -> tuple[int, int, int]:
    clean = value.strip().lstrip("v").split("-", 1)[0]
    parts = clean.split(".")
    if len(parts) != 3:
        raise ValueError(f"Некорректная версия: {value}")
    return tuple(int(part) for part in parts)


class CompatibilityManager:
    def __init__(self, registry: dict):
        self.registry = registry
        with COMPATIBILITY_PATH.open("r", encoding="utf-8") as handle:
            self.rules = json.load(handle)

    def check(self) -> dict:
        results = {}
        all_ok = True

        for core_name, requirements in self.rules.get("requirements", {}).items():
            core_result = {"ok": True, "requirements": {}}

            for dependency, bounds in requirements.items():
                dependency_config = self.registry.get(dependency)
                if not isinstance(dependency_config, dict):
                    item = {
                        "ok": False,
                        "error": "dependency_not_registered",
                    }
                    core_result["requirements"][dependency] = item
                    core_result["ok"] = False
                    all_ok = False
                    continue

                current = str(dependency_config.get("version", "0.0.0"))
                current_tuple = _version_tuple(current)
                minimum = bounds.get("min")
                maximum = bounds.get("max")

                ok = True
                if minimum and current_tuple < _version_tuple(minimum):
                    ok = False
                if maximum and current_tuple > _version_tuple(maximum):
                    ok = False

                item = {
                    "ok": ok,
                    "current": current,
                    "min": minimum,
                    "max": maximum,
                }
                core_result["requirements"][dependency] = item
                if not ok:
                    core_result["ok"] = False
                    all_ok = False

            results[core_name] = core_result

        return {
            "ok": all_ok,
            "cores": results,
        }
