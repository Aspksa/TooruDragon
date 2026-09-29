from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


PROTOCOL_VERSION = "1.0"


@dataclass(frozen=True)
class Envelope:
    protocol: str
    version: str
    id: str
    source: str
    target: str | None
    timestamp: str
    trace_id: str
    payload: dict[str, Any]

    @classmethod
    def create(
        cls,
        protocol: str,
        source: str,
        payload: dict[str, Any] | None = None,
        *,
        target: str | None = None,
        trace_id: str | None = None,
    ) -> "Envelope":
        if not protocol or "." not in protocol:
            raise ValueError("protocol must be a namespaced identifier")
        if not source:
            raise ValueError("source is required")
        return cls(
            protocol=protocol,
            version=PROTOCOL_VERSION,
            id=str(uuid4()),
            source=source,
            target=target,
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=trace_id or str(uuid4()),
            payload=dict(payload or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_envelope(value: dict[str, Any]) -> None:
    required = {
        "protocol": str,
        "version": str,
        "id": str,
        "source": str,
        "timestamp": str,
        "trace_id": str,
        "payload": dict,
    }
    for key, expected in required.items():
        if key not in value:
            raise ValueError(f"missing contract field: {key}")
        if not isinstance(value[key], expected):
            raise TypeError(f"contract field {key!r} must be {expected.__name__}")
