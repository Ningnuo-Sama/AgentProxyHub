#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from core import upstream_fetcher as uf


def node(provider, label="old"):
    return {"node_id": provider + ":" + label, "provider_id": provider, "protocol_config": {"password": "PRIVATE"}}


class Response:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps({"nodes": [{"type": "http", "server": "x", "port": 80}]}).encode()


class UpstreamFetcherTests(unittest.TestCase):
    def test_extract_normalizes_preserves_protocol_and_deduplicates(self):
        payload = {"proxies": [
            {"name": "US-1", "type": "socks5", "server": "edge.example", "port": "443", "password": "a"},
            {"name": "other name", "type": "socks5", "server": "edge.example", "port": 443, "password": "a"},
            {"type": "socks5", "server": "edge.example", "port": 443, "password": "b"},
        ]}
        nodes = uf.extract_nodes(payload, "test", "US")
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0]["protocol_config"]["password"], "a")
        self.assertEqual(nodes[0]["port"], 443)
        self.assertEqual(nodes[0]["country"], "US")
        self.assertEqual(nodes[0]["health"], "UNKNOWN")

    def test_invalid_ports(self):
        for port in (0, -1, 65536, "bad", None):
            self.assertEqual(uf.extract_nodes({"nodes": [{"type": "http", "server": "x", "port": port}]}, "p"), [])

    def test_explicit_endpoint_and_bearer(self):
        seen = {}
        def opener(request, timeout):
            seen.update(url=request.full_url, auth=request.headers.get("Authorization"), timeout=timeout)
            return Response()
        uf.fetch_source({"id": "p", "url": "https://base.test", "token": "secret", "extra": {"fetch_endpoint": "https://endpoint.test/nodes"}}, opener)
        self.assertEqual(seen, {"url": "https://endpoint.test/nodes", "auth": "Bearer secret", "timeout": 30})

    def test_https_only_and_no_userinfo(self):
        for url in ("http://example.test", "file:///tmp/x", "https://user:secret@example.test", "https://"):
            with self.assertRaises(ValueError): uf.fetch_source({"url": url}, lambda *a, **k: self.fail("must not fetch"))

    def test_redirect_rejected(self):
        with self.assertRaises(ValueError): uf._NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.test")

    def test_default_opener_verifies_tls(self):
        with patch.object(uf.urllib.request, "build_opener") as build:
            build.return_value.open.return_value = Response()
            uf.fetch_source({"id": "p", "url": "https://example.test"})
            handlers = build.call_args.args
            self.assertIsInstance(handlers[0], uf._NoRedirect)
            self.assertTrue(handlers[1]._context.check_hostname)
            self.assertEqual(handlers[1]._context.verify_mode, uf.ssl.CERT_REQUIRED)

    def test_bad_and_empty_payloads_are_failure(self):
        for payload in (b"", b"{}", b"{bad", b"[]", b'{"nodes":[]}'):
            class Empty(Response):
                def read(self): return payload
            with self.assertRaises((ValueError, Exception)):
                uf.fetch_source({"id": "p", "url": "https://example.test"}, lambda *a, **k: Empty())

    def run_refresh(self, sources, outcomes, dry_run=False):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "snapshot.json")
            uf.write_snapshot([node("a"), node("b")], path)
            with open(path, "rb") as fh: before = fh.read()
            with patch.object(uf, "SNAPSHOT_FILE", path), patch.object(uf, "fetch_source", side_effect=outcomes):
                result = uf.refresh_sources(sources, dry_run)
            with open(path, "rb") as fh: after = fh.read()
            return result, json.loads(after), before, after

    def test_partial_failure_preserves_other_lkg(self):
        result, saved, _, _ = self.run_refresh([{"id": "a"}, {"id": "b"}], [[node("a", "new")], RuntimeError("offline")])
        self.assertTrue(result["ok"])
        self.assertEqual({n["node_id"] for n in saved["nodes"]}, {"a:new", "b:old"})
        self.assertEqual(result["sources"][1]["status"], "error")

    def test_filtered_refresh_preserves_unrequested_source(self):
        result, saved, _, _ = self.run_refresh([{"id": "a"}], [[node("a", "new")]])
        self.assertEqual({n["node_id"] for n in saved["nodes"]}, {"a:new", "b:old"})
        self.assertEqual(result["total_nodes"], 2)
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertIn("PRIVATE", json.dumps(saved))

    def test_all_failed_leaves_snapshot_byte_identical(self):
        result, _, before, after = self.run_refresh([{"id": "a"}, {"id": "b"}], [RuntimeError("offline"), RuntimeError("offline")])
        self.assertFalse(result["ok"])
        self.assertEqual(before, after)

    def test_no_sources_is_noop(self):
        result, _, before, after = self.run_refresh([], [])
        self.assertTrue(result["ok"])
        self.assertIsNone(result["snapshot_path"])
        self.assertEqual(before, after)

    def test_dry_run_does_not_write(self):
        result, _, before, after = self.run_refresh([{"id": "a"}], [[node("a", "new")]], True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(before, after)

    def test_error_never_contains_credentials_or_url(self):
        result, _, _, _ = self.run_refresh([{"id": "a", "token": "SECRET"}], [RuntimeError("failed https://x.test/?token=SECRET Authorization: SECRET")])
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("https://", json.dumps(result))

    def test_atomic_snapshot_full_protocol_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nested", "snapshot.json")
            uf.write_snapshot([node("a")], path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["nodes"][0]["protocol_config"]["password"], "PRIVATE")
            self.assertEqual(os.listdir(os.path.dirname(path)), ["snapshot.json"])


if __name__ == "__main__": unittest.main()
