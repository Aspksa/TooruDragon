from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class SecretProvider(Protocol):
    def get(self, name: str) -> str | None: ...


@dataclass(frozen=True)
class EnvironmentSecretProvider:
    prefix: str = "TOORUDRAGON_SECRET_"

    @staticmethod
    def _normalize(name: str) -> str:
        return name.upper().replace(".", "_").replace("-", "_")

    def get(self, name: str) -> str | None:
        if not name:
            raise ValueError("secret name is required")
        return os.getenv(f"{self.prefix}{self._normalize(name)}")


class SecretStore:
    def __init__(self, providers: list[SecretProvider] | None = None):
        self.providers = providers or [EnvironmentSecretProvider()]

    def get(self, name: str, *, required: bool = False) -> str | None:
        for provider in self.providers:
            value = provider.get(name)
            if value:
                return value
        if required:
            raise RuntimeError(f"required secret is unavailable: {name}")
        return None

    def metadata(self) -> dict:
        return {
            "providers": [type(provider).__name__ for provider in self.providers],
            "plaintext_persistence": False,
        }
