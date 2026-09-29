from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.system.contracts import Envelope, validate_envelope
from core.system.agent_runtime import AgentRuntime, ToolRouter
from core.system.database import Database
from core.system.event_fabric import EventFabric
from core.system.policy import PolicyEngine
from core.system.workflow import WorkflowEngine


class ContractTests(unittest.TestCase):
    def test_envelope_is_versioned_and_traceable(self):
        envelope = Envelope.create(
            "toorudragon.task",
            "tooru_ai",
            {"kind": "demo"},
            target="work",
        ).to_dict()
        validate_envelope(envelope)
        self.assertEqual(envelope["version"], "1.0")
        self.assertTrue(envelope["trace_id"])
        self.assertEqual(envelope["target"], "work")


class PolicyTests(unittest.TestCase):
    def test_default_deny_and_short_allow_list(self):
        policy = PolicyEngine({
            "_default": "deny",
            "worker": ["workflow.worker", "documents.read"],
        })
        self.assertTrue(policy.decide("worker", "workflow.worker").allowed)
        self.assertFalse(policy.decide("worker", "system.shutdown").allowed)
        self.assertEqual(
            policy.allowed_capabilities("worker"),
            {"workflow.worker", "documents.read"},
        )


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.db.initialize("test")
        self.engine = WorkflowEngine(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_idempotency_returns_existing_task(self):
        first = self.engine.create_task(
            kind="work.document",
            payload={"id": 1},
            idempotency_key="same-request",
        )
        second = self.engine.create_task(
            kind="work.document",
            payload={"id": 2},
            idempotency_key="same-request",
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["payload"], {"id": 1})

    def test_capability_filtered_claim_and_completion(self):
        protected = self.engine.create_task(
            kind="home.command",
            payload={"device": "lamp"},
            required_capability="home.control",
        )
        self.engine.create_task(
            kind="public.noop",
            payload={},
        )

        unprivileged = self.engine.claim(
            worker_id="guest",
            allowed_capabilities=set(),
        )
        self.assertIsNotNone(unprivileged)
        self.assertEqual(unprivileged["kind"], "public.noop")

        privileged = self.engine.claim(
            worker_id="home",
            allowed_capabilities={"home.control"},
        )
        self.assertEqual(privileged["id"], protected["id"])

        running = self.engine.mark_running(protected["id"], "home")
        self.assertEqual(running["state"], "running")

        completed = self.engine.complete(
            protected["id"],
            "home",
            result={"ok": True},
        )
        self.assertEqual(completed["state"], "completed")
        self.assertEqual(completed["result"], {"ok": True})

    def test_failure_retries_until_attempt_budget_exhausted(self):
        task = self.engine.create_task(
            kind="lab.test",
            payload={},
            max_attempts=2,
        )

        claim = self.engine.claim(worker_id="laboratory")
        retried = self.engine.fail(
            claim["id"],
            "laboratory",
            "first failure",
            retry_delay_seconds=0,
        )
        self.assertEqual(retried["state"], "retrying")

        claim2 = self.engine.claim(worker_id="laboratory")
        failed = self.engine.fail(
            claim2["id"],
            "laboratory",
            "second failure",
            retry_delay_seconds=0,
        )
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["attempts"], 2)


    def test_child_waits_for_parent_and_terminal_failure_cascades(self):
        parent = self.engine.create_task(
            kind="workflow.parent",
            payload={},
            max_attempts=1,
        )
        child = self.engine.create_task(
            kind="workflow.child",
            payload={},
            workflow_id=parent["workflow_id"],
            parent_id=parent["id"],
        )

        claimed_parent = self.engine.claim(worker_id="worker")
        self.assertEqual(claimed_parent["id"], parent["id"])

        blocked_child = self.engine.claim(worker_id="other-worker")
        self.assertIsNone(blocked_child)

        failed_parent = self.engine.fail(
            parent["id"],
            "worker",
            "terminal",
            retry_delay_seconds=0,
        )
        self.assertEqual(failed_parent["state"], "failed")
        self.assertEqual(self.engine.get(child["id"])["state"], "cancelled")

    def test_child_becomes_claimable_after_parent_completion(self):
        parent = self.engine.create_task(
            kind="workflow.parent",
            payload={},
        )
        child = self.engine.create_task(
            kind="workflow.child",
            payload={},
            workflow_id=parent["workflow_id"],
            parent_id=parent["id"],
        )

        claimed = self.engine.claim(worker_id="worker")
        self.engine.mark_running(claimed["id"], "worker")
        self.engine.complete(claimed["id"], "worker", result={})

        next_task = self.engine.claim(worker_id="worker")
        self.assertEqual(next_task["id"], child["id"])


class EventFabricTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "events.db")
        self.db.initialize("test")
        self.fabric = EventFabric(self.db, retention=1000)

    def tearDown(self):
        self.tmp.cleanup()

    def test_replay_ack_and_dead_letter(self):
        first = self.fabric.publish("demo.created", "test", {"n": 1})
        second = self.fabric.publish("demo.created", "test", {"n": 2})

        replay = self.fabric.replay("consumer-a", topic="demo.created")
        self.assertEqual([item["id"] for item in replay], [first["id"], second["id"]])

        self.fabric.ack("consumer-a", first["sequence"])
        replay2 = self.fabric.replay("consumer-a", topic="demo.created")
        self.assertEqual([item["id"] for item in replay2], [second["id"]])

        self.fabric.dead_letter(second["id"], "consumer-a", "boom")
        self.assertEqual(self.fabric.stats()["dead_letters"], 1)


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "agents.db")
        self.db.initialize("test")
        self.workflow = WorkflowEngine(self.db)
        self.policy = PolicyEngine({
            "_default": "deny",
            "planner": ["workflow.create"],
        })
        self.runtime = AgentRuntime(
            self.workflow,
            self.policy,
            ToolRouter(self.policy),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_agent_plan_is_policy_gated_and_traceable(self):
        plan = self.runtime.submit_plan(
            agent_id="planner",
            steps=[
                {"kind": "work.prepare", "payload": {"x": 1}},
                {"kind": "work.execute", "payload": {"x": 2}},
            ],
        )
        self.assertEqual(len(plan["tasks"]), 2)
        self.assertEqual(
            plan["tasks"][1]["parent_id"],
            plan["tasks"][0]["id"],
        )
        self.assertEqual(
            plan["tasks"][0]["trace_id"],
            plan["tasks"][1]["trace_id"],
        )

        with self.assertRaises(PermissionError):
            self.runtime.submit_plan(
                agent_id="unknown",
                steps=[{"kind": "noop", "payload": {}}],
            )


if __name__ == "__main__":
    unittest.main()
