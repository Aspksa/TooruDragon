from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsLauncherTests(unittest.TestCase):
    def test_critical_batch_launchers_are_ascii_only(self):
        for relative in (
            "StartTooruDragon.bat",
            "scripts/start_all.bat",
        ):
            data = (ROOT / relative).read_bytes()
            try:
                data.decode("ascii")
            except UnicodeDecodeError as exc:
                self.fail(f"{relative} must remain ASCII-only: {exc}")

    def test_start_all_avoids_nested_cmd_shells(self):
        text = (ROOT / "scripts/start_all.bat").read_text(encoding="ascii")
        self.assertNotIn("cmd /k", text.lower())
        self.assertNotIn("chcp 65001", text.lower())
        self.assertIn('"core\\tooru_ai\\app.py"', text)
        self.assertIn('"web\\server.py"', text)

    def test_root_launcher_uses_absolute_windows_powershell(self):
        text = (ROOT / "StartTooruDragon.bat").read_text(encoding="ascii")
        self.assertIn(
            "%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
            text,
        )
        self.assertNotIn("chcp 65001", text.lower())


if __name__ == "__main__":
    unittest.main()
