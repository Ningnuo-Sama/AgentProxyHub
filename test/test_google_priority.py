import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core import confidence_engine as confidence
from mcp import server


class GooglePriorityTests(unittest.TestCase):
    def test_first_probe_persists_google_and_physical_baselines(self):
        rec = {}
        result = confidence.update_record(
            21015,
            {
                "ok": True,
                "ip": "198.51.100.15",
                "country": "JP",
                "google_country": "UNITED STATES",
                "latency_ms": 20,
            },
            {"ip": "198.51.100.15", "countryCode": "JP", "googleCountry": "United States"},
            rec,
        )
        self.assertEqual(result["baselineIp"], "198.51.100.15")
        self.assertEqual(result["baselineGoogleCountry"], "UNITED STATES")
        self.assertEqual(result["baselinePhysicalCountry"], "JP")
        self.assertTrue(result["stableSince"])

    def test_unknown_google_country_does_not_veto(self):
        rec = {
            "baselineIp": "198.51.100.10",
            "baselineGoogleCountry": "UNITED STATES",
            "baselinePhysicalCountry": "US",
            "stableSince": confidence.now_iso(),
        }
        result = confidence.update_record(
            21015,
            {"ok": True, "ip": "198.51.100.11", "country": "", "google_country": "FAIL", "latency_ms": 20},
            None,
            rec,
        )
        self.assertFalse(result["vetoed"])
        self.assertEqual(result["driftEvents"][-1]["kind"], "unknown")

    def test_google_verify_tool_is_read_only_and_explains_evidence(self):
        body = "<a>Country version:</a> Japan</div>"
        fake = type("Completed", (), {"stdout": body})()
        with patch("subprocess.run", return_value=fake):
            result = server.tool_google_verify_proxy({"port": 21015, "timeout": 3})
        self.assertTrue(result["verified"])
        self.assertEqual(result["googleCountry"], "Japan")
        self.assertIn("Google policies", result["evidence"])

    def test_mcp_data_dir_is_injectable(self):
        with tempfile.TemporaryDirectory() as temp:
            old = server.DATA_DIR
            try:
                server.DATA_DIR = temp
                self.assertEqual(server.load_confidence_index(), {})
                with open(os.path.join(temp, "confidence_state.json"), "w", encoding="utf-8") as f:
                    json.dump({"ports": {"21015": {"tier": "B", "score": 61.5}}}, f)
                self.assertEqual(server.load_confidence_index()["21015"]["tier"], "B")
            finally:
                server.DATA_DIR = old


if __name__ == "__main__":
    unittest.main()
