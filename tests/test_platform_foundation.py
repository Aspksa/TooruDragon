from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.system.contracts import Envelope, validate_envelope
from core.system.agent_runtime import AgentRuntime, Tool, ToolRouter
from core.system.model_router import ModelProviderError, ModelRouter
from core.system.chat_runtime import ChatConfig, ChatRuntime
from core.system.ai_memory import AIMemoryStore
from core.system.database import Database
from core.system.event_fabric import EventFabric
from core.system.observability import Observability
from core.system.policy import PolicyEngine
from core.system.rag import RAGIndex
from core.system.workflow import WorkflowEngine


class DatabaseTransactionTests(unittest.TestCase):
    def test_exception_rolls_back_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tx.db")
            db.initialize("test")
            with self.assertRaises(RuntimeError):
                with db.connect() as conn:
                    conn.execute(
                        "INSERT INTO system_meta(key, value) VALUES(?, ?)",
                        ("should_rollback", "yes"),
                    )
                    raise RuntimeError("force rollback")

            rows = db.query(
                "SELECT value FROM system_meta WHERE key=?",
                ("should_rollback",),
            )
            self.assertEqual(rows, [])


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

    def test_incremental_event_read(self):
        first = self.fabric.publish("stream.test", "test", {"n": 1})
        second = self.fabric.publish("stream.test", "test", {"n": 2})
        items = self.fabric.recent(
            limit=10,
            after_sequence=first["sequence"],
        )
        self.assertEqual([item["id"] for item in items], [second["id"]])



class ObservabilityTests(unittest.TestCase):
    def test_samples_include_timestamp_and_history(self):
        obs = Observability(max_samples=10)
        first = obs.sample()
        second = obs.snapshot()
        self.assertGreater(first["timestamp"], 0)
        self.assertIn("rss_bytes", first)
        self.assertGreaterEqual(len(second["recent"]), 2)



class FakeModelRouter:
    def __init__(self):
        self.last_messages = None

    def chat(self, messages, **kwargs):
        self.last_messages = messages
        return {
            "provider": "fake",
            "model": "fake-model",
            "content": "response",
            "finish_reason": "stop",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "raw_id": "fake-1",
        }

    def status(self):
        return {
            "default_provider": "fake",
            "providers": {
                "fake": {
                    "enabled": True,
                    "secret_available": True,
                }
            },
            "available": True,
        }


class AIRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "ai.db")
        self.db.initialize("test")
        self.memory = AIMemoryStore(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_memory_retrieval_ranks_overlap(self):
        first = self.memory.remember(
            "global",
            "dragon architecture uses a durable event fabric",
            source="test",
        )
        self.memory.remember(
            "global",
            "unrelated grocery shopping note",
            source="test",
        )
        results = self.memory.retrieve(
            "durable event architecture",
            scope="global",
            limit=5,
        )
        self.assertTrue(results)
        self.assertEqual(results[0]["id"], first["id"])
        self.assertGreater(results[0]["score"], 0)

    def test_chat_injects_retrieval_context_and_persists_exchange(self):
        self.memory.remember(
            "global",
            "TooruDragon uses a Gateway for blue green routing",
            source="test",
        )
        router = FakeModelRouter()
        runtime = ChatRuntime(
            router,
            self.memory,
            ChatConfig(
                system_prompt="system prompt",
                history_limit=10,
                retrieval_limit=5,
                memory_scope="global",
            ),
        )

        result = runtime.chat(
            "How does Gateway routing work?",
            trace_id="trace-test",
        )
        history = self.memory.history(result["conversation_id"], limit=10)

        self.assertEqual(result["content"], "response")
        self.assertEqual([item["role"] for item in history], ["user", "assistant"])
        self.assertEqual(history[0]["trace_id"], "trace-test")
        self.assertEqual(history[1]["provider"], "fake")
        self.assertTrue(
            any(
                "Relevant memory context" in item["content"]
                for item in router.last_messages
                if item["role"] == "system"
            )
        )

    def test_rag_ingest_search_and_prompt_injection(self):
        rag = RAGIndex(
            self.db,
            chunk_size=220,
            chunk_overlap=30,
        )
        document = rag.ingest(
            (
                "Gateway routes production traffic between canonical and green candidates. "
                "Supervisor can restore active routes after restart. "
            ) * 8,
            title="Blue Green Notes",
            source="test",
        )
        self.assertGreater(document["chunk_count"], 1)

        found = rag.search("restore gateway candidate routes", limit=5)
        self.assertTrue(found)
        self.assertEqual(found[0]["document_id"], document["id"])

        router = FakeModelRouter()
        runtime = ChatRuntime(
            router,
            self.memory,
            ChatConfig(
                system_prompt="system",
                rag_limit=5,
            ),
            rag=rag,
        )
        result = runtime.chat("How are candidate routes restored?")
        self.assertTrue(result["retrieved_rag"])
        self.assertTrue(
            any(
                "Retrieved document context" in item["content"]
                for item in router.last_messages
                if item["role"] == "system"
            )
        )

    def test_disabled_provider_does_not_persist_exchange(self):
        router = ModelRouter({
            "default_provider": "local",
            "providers": {
                "local": {
                    "type": "openai_compatible",
                    "enabled": False,
                    "base_url": "http://127.0.0.1:9/v1",
                    "model": "test-model",
                }
            },
        })
        runtime = ChatRuntime(
            router,
            self.memory,
            ChatConfig(system_prompt="system"),
        )
        with self.assertRaises(ModelProviderError):
            runtime.chat("hello")

        conversations = self.memory.conversations()
        self.assertEqual(conversations, [])



class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "agents.db")
        self.db.initialize("test")
        self.workflow = WorkflowEngine(self.db)
        self.policy = PolicyEngine({
            "_default": "deny",
            "planner": ["workflow.create", "documents.read"],
        })
        self.router = ToolRouter(self.policy)
        self.router.register(Tool(
            name="demo.read",
            capability="documents.read",
            handler=lambda payload: {"echo": payload.get("value")},
        ))
        self.runtime = AgentRuntime(
            self.workflow,
            self.policy,
            self.router,
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


    def test_tool_router_enforces_capability_policy(self):
        catalog = self.router.catalog("planner")
        self.assertEqual(catalog[0]["name"], "demo.read")

        result = self.router.invoke(
            "planner",
            "demo.read",
            {"value": 42},
        )
        self.assertEqual(result, {"echo": 42})

        with self.assertRaises(PermissionError):
            self.router.invoke(
                "unknown",
                "demo.read",
                {"value": 42},
            )


if __name__ == "__main__":
    unittest.main()
