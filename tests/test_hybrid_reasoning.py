from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.system.ai_memory import AIMemoryStore
from core.system.chat_runtime import ChatConfig, ChatRuntime
from core.system.database import Database
from core.system.reasoning import HybridReasoningEngine, ReasoningConfig
from core.system.reasoning_learning import AdaptiveReasoningStore


class FakeRouter:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        index = len(self.calls)
        content = (
            self.responses.pop(0)
            if self.responses
            else f"response-{index}"
        )
        return {
            "provider": "fake",
            "model": "fake-model",
            "content": content,
            "finish_reason": "stop",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "raw_id": f"fake-{index}",
        }

    def status(self):
        return {
            "default_provider": "fake",
            "providers": {"fake": {"enabled": True}},
            "available": True,
        }


class HybridReasoningEngineTests(unittest.TestCase):
    def test_simple_auto_request_stays_on_chain(self):
        router = FakeRouter()
        engine = HybridReasoningEngine(ReasoningConfig(mode="auto"))
        result, audit = engine.run(
            router,
            [{"role": "user", "content": "Привет"}],
            user_message="Привет",
        )

        self.assertEqual(result["content"], "response-1")
        self.assertEqual(audit["mode"], "chain")
        self.assertEqual(audit["model_calls"], 1)
        self.assertEqual(audit["depth"], 1)
        self.assertEqual(len(router.calls), 1)

    def test_forced_tree_without_adaptation_uses_all_branches(self):
        router = FakeRouter()
        engine = HybridReasoningEngine(
            ReasoningConfig(
                mode="tree",
                max_branches=3,
                adaptive_enabled=False,
            )
        )
        result, audit = engine.run(
            router,
            [{"role": "user", "content": "Проверь документ"}],
            user_message="Проверь документ",
        )

        self.assertEqual(audit["mode"], "tree")
        self.assertEqual(audit["branch_count"], 3)
        self.assertEqual(audit["model_calls"], 4)
        self.assertEqual(audit["verification_rounds"], 0)
        self.assertEqual(len(router.calls), 4)
        self.assertEqual(result["content"], "response-4")
        self.assertTrue(all("content" not in item for item in audit["branches"]))

    def test_verify_verdict_triggers_bounded_extra_depth(self):
        router = FakeRouter([
            "evidence",
            "alternatives",
            "VERDICT: VERIFY\nmaterial conflict",
            "VERDICT: CLEAR\nconflict resolved",
            "final answer",
        ])
        engine = HybridReasoningEngine(
            ReasoningConfig(
                mode="tree",
                max_branches=3,
                adaptive_enabled=True,
                max_depth=3,
            )
        )
        result, audit = engine.run(
            router,
            [{"role": "user", "content": "Проверь противоречия"}],
            user_message="Проверь противоречия",
        )

        self.assertEqual(result["content"], "final answer")
        self.assertEqual(audit["mode"], "tree")
        self.assertEqual(audit["depth"], 2)
        self.assertEqual(audit["verification_rounds"], 1)
        self.assertTrue(audit["contradiction_detected"])
        self.assertIn(
            "branch_requested_verification",
            audit["verification_triggers"],
        )
        self.assertEqual(audit["model_calls"], 5)
        self.assertEqual(len(router.calls), 5)


class AdaptiveReasoningStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "learning.db")
        self.db.initialize("test")
        self.store = AdaptiveReasoningStore(
            self.db,
            learning_rate=0.2,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, mode, branch_name):
        return self.store.record_run(
            trace_id=None,
            mode=mode,
            score=5 if mode == "tree" else 1,
            threshold=4,
            branches=[{"name": branch_name, "status": "completed"}],
            depth=1,
            contradiction_detected=False,
            fallback=False,
        )

    def test_feedback_changes_branch_weight_and_order(self):
        critic = self._run("tree", "critic")
        evidence = self._run("tree", "evidence")
        self.store.record_feedback(critic, 1.0)
        self.store.record_feedback(evidence, -1.0)

        order = self.store.branch_order(["evidence", "critic"])
        stats = self.store.stats()

        self.assertEqual(order[0], "critic")
        weights = {
            item["branch_name"]: item["weight"]
            for item in stats["branches"]
        }
        self.assertGreater(weights["critic"], weights["evidence"])

    def test_mode_feedback_can_adjust_auto_threshold(self):
        for _ in range(3):
            run_id = self._run("tree", "critic")
            self.store.record_feedback(run_id, 1.0)
        for _ in range(3):
            run_id = self._run("chain", "evidence")
            self.store.record_feedback(run_id, -1.0)

        self.assertEqual(
            self.store.threshold_adjustment(min_feedback=3),
            -1,
        )

    def test_feedback_overwrite_is_idempotent_for_count(self):
        run_id = self._run("tree", "critic")
        self.store.record_feedback(run_id, 1.0)
        self.store.record_feedback(run_id, 0.5)
        stats = self.store.stats()
        tree = next(item for item in stats["modes"] if item["mode"] == "tree")
        self.assertEqual(tree["feedback_count"], 1)
        self.assertAlmostEqual(tree["feedback_sum"], 0.5)


class ChatRuntimeReasoningTests(unittest.TestCase):
    def test_chat_persists_run_and_accepts_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "reasoning.db")
            db.initialize("test")
            memory = AIMemoryStore(db)
            router = FakeRouter()
            runtime = ChatRuntime(
                router,
                memory,
                ChatConfig(
                    system_prompt="system",
                    reasoning_mode="tree",
                    reasoning_max_branches=2,
                    reasoning_adaptive_enabled=True,
                    reasoning_max_depth=2,
                ),
            )

            result = runtime.chat("Проверь документ")
            run_id = result["reasoning"].get("run_id")
            self.assertTrue(run_id)
            self.assertTrue(result["reasoning"]["learning_persisted"])

            feedback = runtime.reasoning_feedback(run_id, 1.0)
            stats = runtime.reasoning_stats()
            status = runtime.status()

            self.assertEqual(feedback["feedback_score"], 1.0)
            self.assertTrue(stats["enabled"])
            self.assertTrue(stats["recent_runs"])
            self.assertEqual(status["reasoning"]["mode"], "tree")
            self.assertEqual(status["reasoning"]["max_depth"], 2)


if __name__ == "__main__":
    unittest.main()
