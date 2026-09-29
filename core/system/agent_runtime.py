from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .policy import PolicyEngine
from .workflow import WorkflowEngine


@dataclass(frozen=True)
class Tool:
    name: str
    capability: str
    handler: Callable[[dict], dict]


class ToolRouter:
    def __init__(self, policy: PolicyEngine):
        self.policy = policy
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def invoke(self, subject: str, name: str, payload: dict) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(name)
        self.policy.require(subject, tool.capability)
        return tool.handler(dict(payload))

    def catalog(self, subject: str) -> list[dict]:
        result = []
        for tool in self._tools.values():
            if self.policy.decide(subject, tool.capability).allowed:
                result.append({
                    "name": tool.name,
                    "capability": tool.capability,
                })
        return result


class AgentRuntime:
    def __init__(
        self,
        workflow: WorkflowEngine,
        policy: PolicyEngine,
        tools: ToolRouter,
    ):
        self.workflow = workflow
        self.policy = policy
        self.tools = tools

    def submit_plan(
        self,
        *,
        agent_id: str,
        steps: list[dict],
        trace_id: str | None = None,
    ) -> dict:
        self.policy.require(agent_id, "workflow.create")
        if not steps:
            raise ValueError("plan requires at least one step")

        workflow_id = None
        created = []
        parent_id = None
        for index, step in enumerate(steps):
            kind = str(step.get("kind", "")).strip()
            if not kind:
                raise ValueError(f"step {index} has no kind")
            task = self.workflow.create_task(
                kind=kind,
                payload=step.get("payload", {}),
                workflow_id=workflow_id,
                parent_id=parent_id,
                priority=int(step.get("priority", 100)),
                max_attempts=int(step.get("max_attempts", 3)),
                idempotency_key=step.get("idempotency_key"),
                trace_id=trace_id,
                required_capability=step.get("required_capability"),
            )
            workflow_id = task["workflow_id"]
            parent_id = task["id"]
            trace_id = task["trace_id"]
            created.append(task)

        return {
            "agent_id": agent_id,
            "workflow_id": workflow_id,
            "trace_id": trace_id,
            "tasks": created,
        }
