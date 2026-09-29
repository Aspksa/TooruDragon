from __future__ import annotations

import unittest

from web.server import _allowed


class WebControlCenterProxyTests(unittest.TestCase):
    def test_main_read_routes_are_allowlisted(self):
        self.assertTrue(_allowed("GET", "main", "/api/cores"))
        self.assertTrue(_allowed("GET", "main", "/api/tasks?limit=100"))
        self.assertTrue(_allowed("GET", "main", "/observability"))
        self.assertTrue(_allowed("GET", "tooru_ai", "/runtime"))
        self.assertTrue(_allowed("GET", "tooru_ai", "/memory/search?q=gateway"))
        self.assertTrue(_allowed("GET", "tooru_ai", "/rag/search?q=gateway"))
        self.assertTrue(_allowed("GET", "tooru_ai", "/rag/documents"))
        self.assertTrue(_allowed("GET", "main", "/api/task/transitions?task_id=abc"))

    def test_control_actions_are_explicitly_allowlisted(self):
        self.assertTrue(_allowed("POST", "supervisor", "/core/action"))
        self.assertTrue(_allowed("POST", "supervisor", "/safe-mode/enable"))
        self.assertTrue(_allowed("POST", "main", "/agents/tool/invoke"))
        self.assertTrue(_allowed("POST", "tooru_ai", "/chat"))
        self.assertTrue(_allowed("POST", "tooru_ai", "/memory/remember"))
        self.assertTrue(_allowed("POST", "tooru_ai", "/rag/ingest"))

    def test_arbitrary_local_proxying_is_rejected(self):
        self.assertFalse(_allowed("GET", "main", "/system"))
        self.assertFalse(_allowed("POST", "main", "/registry/register"))
        self.assertFalse(_allowed("GET", "gateway", "/core/home/health"))
        self.assertFalse(_allowed("POST", "supervisor", "/unknown"))
        self.assertFalse(_allowed("POST", "tooru_ai", "/arbitrary"))

    def test_wrong_method_is_rejected(self):
        self.assertFalse(_allowed("POST", "main", "/api/cores"))
        self.assertFalse(_allowed("GET", "supervisor", "/core/action"))


if __name__ == "__main__":
    unittest.main()
