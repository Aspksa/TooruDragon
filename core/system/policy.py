from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


class PolicyEngine:
    def __init__(self, policies: dict | None = None):
        self.policies = policies or {}

    def decide(self, subject: str, capability: str) -> Decision:
        if not subject or not capability:
            return Decision(False, "subject_and_capability_required")

        subject_policy = self.policies.get(subject, {})
        if isinstance(subject_policy, list):
            denied = set()
            allowed = set(subject_policy)
        elif isinstance(subject_policy, dict):
            denied = set(subject_policy.get("deny", []))
            allowed = set(subject_policy.get("allow", []))
        else:
            denied = set()
            allowed = set()

        if capability in denied or "*" in denied:
            return Decision(False, "explicit_deny")
        if capability in allowed or "*" in allowed:
            return Decision(True, "explicit_allow")

        default = str(self.policies.get("_default", "deny")).lower()
        return Decision(default == "allow", f"default_{default}")

    def require(self, subject: str, capability: str) -> None:
        decision = self.decide(subject, capability)
        if not decision.allowed:
            raise PermissionError(
                f"policy denied {subject!r} capability {capability!r}: {decision.reason}"
            )

    def snapshot(self) -> dict:
        return {
            "default": self.policies.get("_default", "deny"),
            "subjects": sorted(key for key in self.policies if key != "_default"),
        }
