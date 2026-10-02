"""A-05/A-03：隔离目录中的多进程、崩溃注入与配置故障测试。"""
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import bindings_store as store
from provider_refresh import refresh_provider
from recovery_policy import same_region_candidate


def configure(directory):
    store.DATA_DIR = directory
    for attr, filename in [("BINDINGS_FILE", "bindings.json"), ("REVISION_FILE", "bindings.revision"), ("LOCK_FILE", "bindings.lock"), ("JOURNAL_FILE", "bindings.journal")]:
        setattr(store, attr, os.path.join(directory, filename))


def bind_worker(directory, port):
    configure(directory)
    store.bind("profile-" + str(port), port)


def cas_worker(directory, start, results, port):
    configure(directory)
    start.wait(10)
    try:
        store.write({str(port): {"profile": "p"}}, expected_revision=0)
        results.put("committed")
    except RuntimeError:
        results.put("conflict")


class FocusedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        configure(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_multiprocess_bind_preserves_every_writer(self):
        ctx = multiprocessing.get_context("spawn")
        workers = [ctx.Process(target=bind_worker, args=(self.temp.name, 21001+i)) for i in range(6)]
        for p in workers: p.start()
        for p in workers:
            p.join(25)
            self.assertFalse(p.is_alive())
            self.assertEqual(p.exitcode, 0)
        data, rev = store.read_with_revision()
        self.assertEqual(set(data), {str(21001+i) for i in range(6)})
        self.assertEqual(rev, 6)

    def test_multiprocess_cas_exactly_one_commit(self):
        ctx = multiprocessing.get_context("spawn")
        start = ctx.Event(); results = ctx.Queue()
        workers = [ctx.Process(target=cas_worker, args=(self.temp.name, start, results, 21001+i)) for i in range(2)]
        for p in workers: p.start()
        start.set()
        for p in workers:
            p.join(25)
            self.assertEqual(p.exitcode, 0)
        self.assertEqual(sorted([results.get(timeout=3), results.get(timeout=3)]), ["committed", "conflict"])
        self.assertEqual(store.read_with_revision()[1], 1)
        results.close(); results.join_thread()

    def test_crash_after_each_replace_recovers_same_transaction(self):
        original = os.replace
        for crash_after in (1, 2, 3):
            with self.subTest(crash_after=crash_after), tempfile.TemporaryDirectory() as directory:
                configure(directory)
                count = 0
                def crash_replace(src, dst):
                    nonlocal count
                    original(src, dst); count += 1
                    if count == crash_after: raise OSError("simulated process interruption")
                expected = {"21001": {"profile": "crash-test"}}
                with patch.object(store.os, "replace", side_effect=crash_replace):
                    with self.assertRaises(OSError): store.write(expected, 0)
                self.assertEqual(store.read_with_revision(), (expected, 1))
                self.assertFalse(os.path.exists(store.JOURNAL_FILE))
        configure(self.temp.name)

    def test_corrupt_existing_json_not_overwritten(self):
        Path(store.BINDINGS_FILE).write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError): store.write({})
        self.assertEqual(Path(store.BINDINGS_FILE).read_text(), "{broken")

    def test_bad_yaml_with_root_key_is_rejected(self):
        target = os.path.join(self.temp.name, "provider.yaml")
        malformed = "proxies:\n - {name: broken, [\n" + "# padding\n" * 50
        with self.assertRaises(ValueError): refresh_provider(target, lambda: malformed)
        self.assertFalse(os.path.exists(target))

    def test_reload_exception_restores_exact_old_bytes(self):
        target = os.path.join(self.temp.name, "provider.yaml")
        old = "proxies:\n" + (" - name: old\n   server: example.com\n   port: 443\n   type: socks5\n" * 5)
        new = old.replace("old", "new")
        Path(target).write_text(old, encoding="utf-8")
        original_bytes = Path(target).read_bytes()
        def fail(): raise OSError("reload failure")
        with self.assertRaises(RuntimeError): refresh_provider(target, lambda: new, reload=fail)
        self.assertEqual(Path(target).read_bytes(), original_bytes)

    def test_provider_validation_and_kernel_gate(self):
        target = os.path.join(self.temp.name, "provider.yaml")
        valid = "proxies:\n - name: n\n   server: example.com\n   port: 443\n   type: socks5\n"
        with self.assertRaises(ValueError): refresh_provider(target, lambda: valid, validate=lambda _: None)
        with self.assertRaises(ValueError): refresh_provider(target, lambda: valid, kernel_validate=lambda _: False)
        self.assertFalse(os.path.exists(target))
        with self.assertRaises(ValueError): refresh_provider(target, lambda: "proxies:\n - name: n\n   server: e\n   port: 443.0\n   type: socks5\n")

    def test_both_countries_known_and_normalized(self):
        candidate = {"Country": " US ", "GoogleCountry": "United States", "Latency": 10}
        for key in ("country", "googleCountry"):
            for unknown in (None, "", "Unknown", " FAIL "):
                dead = {"country": "US", "googleCountry": "United States", key: unknown}
                self.assertIsNone(same_region_candidate(dead, [candidate]))
        self.assertEqual(same_region_candidate({"country": "us", "googleCountry": " united   states "}, [candidate]), candidate)

if __name__ == "__main__":
    unittest.main()
