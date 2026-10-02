import copy
import json
import tempfile
import unittest
from pathlib import Path

from core.personal_route import (build_candidate, fixed_listener_map, candidate_summary,
                                 read_manual_halt, activation_preflight, runtime_controller_auth)


def fixture():
    ports = list(range(21001, 21081)) + list(range(22001, 22046))
    return {"secret": "TEST_ONLY_NOT_A_REAL_SECRET", "interface-name": "WLAN",
            "external-controller": "127.0.0.1:21909", "mode": "rule",
            "listeners": [{"name": "in-rule-phone", "port": 39999, "type": "mixed"}] +
            [{"port": p, "type": "socks", "proxy": ("fw-" if p < 22000 else "xc-") + str(p)} for p in ports],
            "proxy-groups": [{"name": "AUTO-POOL", "type": "url-test", "proxies": ["fw-21001"]}],
            "rules": ["MATCH,AUTO-POOL"]}


class PersonalRouteTests(unittest.TestCase):
    def test_125_fixed_mappings_and_all_listeners_unchanged(self):
        config = fixture()
        original = copy.deepcopy(config)
        candidate = build_candidate(config)
        self.assertEqual(125, len(fixed_listener_map(candidate)))
        self.assertEqual(config["listeners"], candidate["listeners"])
        self.assertEqual(original, config)

    def test_personal_rules_and_disabled_tun(self):
        c = build_candidate(fixture())
        self.assertEqual("MATCH,PERSONAL", c["rules"][-1])
        self.assertIn("GEOSITE,cn,DIRECT", c["rules"])
        self.assertFalse(c["tun"]["enable"])
        self.assertTrue(c["tun"]["auto-route"])
        self.assertTrue(c["tun"]["auto-detect-interface"])
        self.assertEqual(["any:53"], c["tun"]["dns-hijack"])
        self.assertEqual("fake-ip", c["dns"]["enhanced-mode"])
        self.assertIn("+.cn", c["dns"]["fake-ip-filter"])
        self.assertIn("127.0.0.0/8", c["tun"]["route-exclude-address"])
        self.assertIn("192.168.0.0/16", c["tun"]["route-exclude-address"])
        self.assertNotIn("strict-route", c["tun"])

    def test_idempotent_transform(self):
        c = build_candidate(fixture())
        self.assertEqual(c, build_candidate(c))

    def test_summary_no_secret(self):
        c = build_candidate(fixture())
        text = json.dumps(candidate_summary(c))
        self.assertNotIn("TEST_ONLY_NOT_A_REAL_SECRET", text)
        self.assertNotIn("secret", text)

    def test_mapping_change_refused(self):
        c = fixture()
        c["listeners"][1]["proxy"] = "AUTO-POOL"
        with self.assertRaises(ValueError):
            build_candidate(c)

    def test_missing_port_refused(self):
        c = fixture()
        c["listeners"].pop()
        with self.assertRaises(ValueError):
            build_candidate(c)

    def test_manual_halt_and_corruption_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "halt.json"
            self.assertFalse(read_manual_halt(state))
            state.write_text('{"manual_halt":true}', encoding="utf-8")
            self.assertEqual("manual_halt", activation_preflight(fixture(), state, privileged=True)["code"])
            state.write_text("broken", encoding="utf-8")
            self.assertTrue(read_manual_halt(state))
            state.write_text('{"manual_halt":false}', encoding="utf-8")
            self.assertFalse(read_manual_halt(state))

    def test_no_privilege_refuses_enable(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "halt.json"
            result = activation_preflight(fixture(), state)
            self.assertEqual("privilege_required", result["code"])
            self.assertFalse(result["applied"])
            ready = activation_preflight(fixture(), state, privileged=True)
            self.assertTrue(ready["ok"])
            self.assertFalse(ready["applied"])
            self.assertFalse(ready["summary"]["tun_enabled"])

    def test_shared_halt_blocks_start(self):
        from unittest.mock import patch
        from core.personal_route import start
        with patch('core.kernel_control.is_halted', return_value=True):
            self.assertEqual('manual_halt', start()['code'])
        with patch('core.kernel_control.is_halted', return_value=False):
            self.assertEqual('privilege_required', start()['code'])
            self.assertFalse(start()['applied'])

    def test_auth_from_runtime_yaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.yaml"
            path.write_text(yaml.safe_dump(fixture()), encoding="utf-8")
            endpoint, headers = runtime_controller_auth(path)
            self.assertEqual("http://127.0.0.1:21909", endpoint)
            self.assertEqual("Bearer TEST_ONLY_NOT_A_REAL_SECRET", headers["Authorization"])
            config = fixture()
            config["external-controller"] = "0.0.0.0:21909"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")
            with self.assertRaises(ValueError):
                runtime_controller_auth(path)


if __name__ == "__main__":
    unittest.main()
