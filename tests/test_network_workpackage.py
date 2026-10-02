#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
from bindings_store import bind, read_with_revision, write
from provider_refresh import refresh_provider, validate_provider_payload
from recovery_policy import same_region_candidate, restart_plan


class NetworkWorkpackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import bindings_store
        bindings_store.DATA_DIR = self.tmp.name
        bindings_store.BINDINGS_FILE = os.path.join(self.tmp.name, "bindings.json")
        bindings_store.LOCK_FILE = os.path.join(self.tmp.name, "bindings.lock")
        bindings_store.REVISION_FILE = os.path.join(self.tmp.name, "bindings.revision")
        bindings_store.JOURNAL_FILE = os.path.join(self.tmp.name, "bindings.journal")

    def tearDown(self):
        self.tmp.cleanup()

    def test_revision_and_concurrent_bindings(self):
        errors = []
        def worker(port):
            try:
                bind("p" + str(port), port)
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker, args=(21001 + i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        data, revision = read_with_revision()
        self.assertFalse(errors)
        self.assertEqual(len(data), 8)
        self.assertEqual(revision, 8)

    def test_cas_conflict_does_not_overwrite(self):
        self.assertEqual(write({}, expected_revision=0), 1)
        with self.assertRaises(RuntimeError):
            write({"21001": {"profile": "x"}}, expected_revision=0)
        data, revision = read_with_revision()
        self.assertEqual(data, {})
        self.assertEqual(revision, 1)

    def test_port_ranges_are_enforced(self):
        with self.assertRaises(ValueError):
            bind("bad", 20001)

    def test_provider_bad_payload_preserves_current(self):
        target = os.path.join(self.tmp.name, "provider.yaml")
        good = "proxies:\n" + ("  - name: n\n    server: example.com\n    port: 443\n    type: socks5\n" * 10)
        refresh_provider(target, lambda: good)
        with open(target, "rb") as fh:
            before = fh.read()
        with self.assertRaises(ValueError):
            refresh_provider(target, lambda: "<html>403 Forbidden</html>")
        with open(target, "rb") as fh:
            self.assertEqual(fh.read(), before)

    def test_recovery_rejects_cross_country_fallback(self):
        dead = {"country": "US", "googleCountry": "United States"}
        candidates = [{"Port": 22001, "Country": "GB", "GoogleCountry": "United Kingdom", "Latency": 1}]
        self.assertIsNone(same_region_candidate(dead, candidates))

    def test_restart_requires_exact_identity_and_only_returns_plan(self):
        good = {"pid": 32272, "name": "mihomo.exe", "path": r"D:\\Program Files\\AgentProxyHub\\bin\\mihomo.exe"}
        plan = restart_plan(good, "mihomo.exe", r"D:\\Program Files\\AgentProxyHub\\bin\\mihomo.exe")
        self.assertEqual(plan["action"], "restart")
        bad = restart_plan({"pid": 32272, "name": "mihomo.exe", "path": r"C:\\other.exe"}, "mihomo.exe", r"D:\\Program Files\\AgentProxyHub\\bin\\mihomo.exe")
        self.assertEqual(bad["action"], "escalate")

    def test_corrupt_revision_rejects_write(self):
        import bindings_store
        with open(bindings_store.REVISION_FILE, "w", encoding="ascii") as fh:
            fh.write("not-a-revision")
        with self.assertRaises(ValueError):
            write({}, expected_revision=0)

    def test_journal_recovers_after_interrupted_commit(self):
        import bindings_store
        data = {"21001": {"profile": "recovered"}}
        with open(bindings_store.JOURNAL_FILE, "w", encoding="utf-8") as fh:
            json.dump({"data": data, "revision": 4}, fh)
        result, revision = read_with_revision()
        self.assertEqual(result, data)
        self.assertEqual(revision, 4)

    def test_provider_reload_failure_restores_backup(self):
        target = os.path.join(self.tmp.name, "provider.yaml")
        good = "proxies:\n" + ("  - name: n\n    server: example.com\n    port: 443\n    type: socks5\n" * 10)
        refresh_provider(target, lambda: good)
        with self.assertRaises(RuntimeError):
            refresh_provider(target, lambda: good.replace("name: n", "name: m"), reload=lambda: False)
        with open(target, encoding="utf-8") as fh:
            self.assertIn("name: n", fh.read())

    def test_provider_atomic_refresh(self):
        target = os.path.join(self.tmp.name, "provider.yaml")
        payload = "proxies:\n" + ("  - name: n\n    server: example.com\n    port: 443\n    type: socks5\n" * 10)
        result = refresh_provider(target, lambda: payload)
        self.assertTrue(result["changed"])
        with open(target, encoding="utf-8") as fh:
            self.assertEqual(validate_provider_payload(fh.read())["sha256"], result["sha256"])


if __name__ == "__main__":
    unittest.main()
