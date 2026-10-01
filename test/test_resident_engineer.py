#!/usr/bin/env python3
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from core.resident_engineer import ALLOWED_ACTIONS, ResidentEngineer


class ResidentEngineerTests(unittest.TestCase):
    def test_health_check_reports_components_and_port(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            nodes = root / "nodes.json"
            nodes.write_text(json.dumps({"nodes": []}), encoding="utf-8")
            state = root / "state.json"
            engineer = ResidentEngineer(state, nodes_file=nodes)
            server = socket.socket()
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            try:
                port = server.getsockname()[1]
                result = engineer.health_check([port, 1])
                self.assertTrue(result["components"]["nodes_file"]["ok"])
                self.assertTrue(result["components"]["state"]["ok"])
                self.assertTrue(next(row for row in result["ports"] if row["port"] == port)["open"])
                self.assertFalse(next(row for row in result["ports"] if row["port"] == 1)["open"])
            finally:
                server.close()

    def test_prompt_and_allowlist(self):
        with tempfile.TemporaryDirectory() as folder:
            e = ResidentEngineer(Path(folder) / "state.json")
            self.assertTrue(e.prompt()["ok"])
            self.assertFalse(e.prompt("missing")["ok"])
            self.assertTrue({"health_check", "read_state", "record_event", "recover_mihomo"}.issubset(ALLOWED_ACTIONS))
            denied = e.dispatch("run_shell", {})
            self.assertEqual(denied["code"], "action_not_allowed")
            self.assertTrue(denied["recoverable"])

    def test_state_persists_and_failure_is_recoverable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            e = ResidentEngineer(path, nodes_file=Path(folder) / "missing.json")
            saved = e.dispatch("record_event", {"type": "probe", "details": {"ok": True}})
            self.assertTrue(saved["ok"])
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["events"]), 1)
            broken = ResidentEngineer(path, nodes_file=Path(folder) / "missing.json")
            result = broken.dispatch("health_check", {"ports": ["bad"]})
            self.assertTrue(result["ok"])
            self.assertFalse(result["result"]["ports"][0]["open"])
            self.assertIn("error", result["result"]["ports"][0])


if __name__ == "__main__":
    unittest.main()
