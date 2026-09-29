from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.system.contracts import Envelope, validate_envelope
from core.system.database import Database
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


if __name__ == "__main__":
    unittest.main()
