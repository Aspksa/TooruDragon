from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .secrets import SecretStore


class ModelProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    kind: str
    base_url: str
    model: str
    enabled: bool
    api_key_secret: str | None
    timeout_seconds: int
    temperature: float
    max_tokens: int | None


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig, secrets: SecretStore):
        self.config = config
        self.secrets = secrets

    def chat(self, messages: list[dict[str, str]], **overrides: Any) -> dict:
        if not self.config.enabled:
            raise ModelProviderError(f"provider_disabled:{self.config.name}")

        model = str(overrides.get("model") or self.config.model).strip()
        if not model:
            raise ModelProviderError(f"provider_model_missing:{self.config.name}")

        temperature = float(overrides.get("temperature", self.config.temperature))
        if not 0.0 <= temperature <= 2.0:
            raise ModelProviderError("temperature_out_of_range")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        max_tokens = overrides.get("max_tokens", self.config.max_tokens)
        if max_tokens is not None:
            max_tokens = int(max_tokens)
            if not 1 <= max_tokens <= 131072:
                raise ModelProviderError("max_tokens_out_of_range")
            payload["max_tokens"] = max_tokens

        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        }
        if self.config.api_key_secret:
            key = self.secrets.get(self.config.api_key_secret)
            if not key:
                raise ModelProviderError(
                    f"provider_secret_missing:{self.config.api_key_secret}"
                )
            headers["Authorization"] = f"Bearer {key}"

        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=max(1, self.config.timeout_seconds),
            ) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ModelProviderError(
                f"provider_http_error:{exc.code}:{body[:500]}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ModelProviderError(f"provider_unavailable:{exc}") from exc

        try:
            data = json.loads(raw)
            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content")
            if not isinstance(content, str):
                raise KeyError("content")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ModelProviderError("provider_invalid_response") from exc

        return {
            "provider": self.config.name,
            "model": data.get("model", model),
            "content": content,
            "finish_reason": choice.get("finish_reason"),
            "usage": data.get("usage"),
            "raw_id": data.get("id"),
        }


class ModelRouter:
    def __init__(
        self,
        config: dict | None = None,
        *,
        secrets: SecretStore | None = None,
    ):
        config = config or {}
        self.secrets = secrets or SecretStore()
        self.default_provider = str(config.get("default_provider", "")).strip()
        self.providers: dict[str, OpenAICompatibleProvider] = {}

        for name, raw in dict(config.get("providers", {})).items():
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("type", "openai_compatible")).strip()
            if kind != "openai_compatible":
                continue
            provider_config = ProviderConfig(
                name=str(name),
                kind=kind,
                base_url=str(raw.get("base_url", "")).strip(),
                model=str(raw.get("model", "")).strip(),
                enabled=bool(raw.get("enabled", False)),
                api_key_secret=(
                    str(raw.get("api_key_secret")).strip()
                    if raw.get("api_key_secret")
                    else None
                ),
                timeout_seconds=int(raw.get("timeout_seconds", 60)),
                temperature=float(raw.get("temperature", 0.3)),
                max_tokens=(
                    int(raw["max_tokens"])
                    if raw.get("max_tokens") is not None
                    else None
                ),
            )
            if not provider_config.base_url:
                continue
            self.providers[str(name)] = OpenAICompatibleProvider(
                provider_config,
                self.secrets,
            )

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        selected = str(provider or self.default_provider).strip()
        if not selected:
            raise ModelProviderError("provider_not_configured")
        implementation = self.providers.get(selected)
        if implementation is None:
            raise ModelProviderError(f"unknown_provider:{selected}")

        overrides: dict[str, Any] = {}
        if model:
            overrides["model"] = model
        if temperature is not None:
            overrides["temperature"] = temperature
        if max_tokens is not None:
            overrides["max_tokens"] = max_tokens
        return implementation.chat(messages, **overrides)

    def status(self) -> dict:
        providers = {}
        for name, provider in self.providers.items():
            cfg = provider.config
            providers[name] = {
                "type": cfg.kind,
                "base_url": cfg.base_url,
                "model": cfg.model,
                "enabled": cfg.enabled,
                "model_configured": bool(cfg.model),
                "requires_secret": bool(cfg.api_key_secret),
                "secret_available": (
                    bool(self.secrets.get(cfg.api_key_secret))
                    if cfg.api_key_secret
                    else True
                ),
            }
        return {
            "default_provider": self.default_provider or None,
            "providers": providers,
            "available": any(
                item["enabled"]
                and item["secret_available"]
                and item["model_configured"]
                for item in providers.values()
            ),
        }
