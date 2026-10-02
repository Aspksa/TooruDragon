from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.system.ai_memory import AIMemoryStore
from core.system.chat_runtime import ChatConfig, ChatRuntime
from core.system.database import Database
from core.system.reasoning import HybridReasoningEngine, ReasoningConfig


class FakeRouter:
    def __init__(self):
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return {
            "provider": "fake",
            "model": "fake-model",
            "content": f"response-{len(self.calls)}",
            "finish_reason": "stop",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "raw_id": f"fake-{len(self.calls)}",
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
        self.assertEqual(len(router.calls), 1)

    def test_complex_auto_request_switches_to_tree(self):
        router = FakeRouter()
        engine = HybridReasoningEngine(
            ReasoningConfig(mode="auto", tree_threshold=4, max_branches=3)
        )
        message = (
            "Сравни два договора, проверь противоречия, проанализируй документы, "
            "объясни почему и предложи варианты? Какие ошибки?"
        )
        result, audit = engine.run(
            router,
            [{"role": "user", "content": message}],
            user_message=message,
            evidence_count=4,
        )

        self.assertEqual(audit["mode"], "tree")
        self.assertEqual(audit["branch_count"], 3)
        self.assertEqual(audit["model_calls"], 4)
        self.assertEqual(len(router.calls), 4)
        self.assertEqual(result["content"], "response-4")
        self.assertTrue(all("content" not in item for item in audit["branches"]))

    def test_forced_tree_can_limit_branch_budget(self):
        router = FakeRouter()
        engine = HybridReasoningEngine(
            ReasoningConfig(mode="tree", max_branches=2)
        )
        _, audit = engine.run(
            router,
            [{"role": "user", "content": "Короткий запрос"}],
            user_message="Короткий запрос",
        )

        self.assertEqual(audit["mode"], "tree")
        self.assertEqual(audit["branch_count"], 2)
        self.assertEqual(audit["model_calls"], 3)
        self.assertEqual(len(router.calls), 3)


class ChatRuntimeReasoningTests(unittest.TestCase):
    def test_chat_exposes_safe_reasoning_audit_and_status(self):
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
                ),
            )

            result = runtime.chat("Проверь документ")
            status = runtime.status()

            self.assertEqual(result["reasoning"]["mode"], "tree")
            self.assertEqual(result["reasoning"]["branch_count"], 2)
            self.assertEqual(len(router.calls), 3)
            self.assertEqual(status["reasoning"]["mode"], "tree")
            self.assertEqual(status["reasoning"]["max_branches"], 2)


if __name__ == "__main__":
    unittest.main()
