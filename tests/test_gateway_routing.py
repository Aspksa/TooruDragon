from __future__ import annotations

import unittest

from gateway import app as gateway_app


class GatewayRoutingTests(unittest.TestCase):
    def test_promote_is_atomic_and_reversible(self):
        original = gateway_app.route_for("home")
        try:
            promoted = gateway_app.promote(
                "home",
                "127.0.0.1",
                8899,
                "green",
            )
            active = gateway_app.route_for("home")

            self.assertEqual(promoted["previous"], original)
            self.assertEqual(active["port"], 8899)
            self.assertEqual(active["slot"], "green")
            self.assertGreaterEqual(promoted["generation"], 2)
        finally:
            gateway_app.promote(
                "home",
                original["host"],
                original["port"],
                original["slot"],
            )

    def test_invalid_route_is_rejected(self):
        with self.assertRaises(ValueError):
            gateway_app.promote(
                "home",
                "127.0.0.1",
                70000,
                "invalid",
            )


if __name__ == "__main__":
    unittest.main()
