#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core import upstream_fetcher as uf


class UpstreamFetcherTests(unittest.TestCase):
    def test_extract_nodes_normalizes_and_deduplicates(self):
        payload = {"proxies": [
            {"name": "US-1", "type": "socks5", "server": "edge.example", "port": "443"},
            {"name": "US-1 duplicate", "type": "socks5", "server": "edge.example", "port": 443},
            {"name": "bad", "type": "unknown", "server": "bad.example", "port": 1},
        ]}
        nodes = uf.extract_nodes(payload, "test", "US")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["country"], "US")
        self.assertEqual(nodes[0]["port"], 443)
        self.assertEqual(nodes[0]["health"], "UNKNOWN")

    def test_fetch_source_sends_bearer_header(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({"nodes": [{"type": "http", "server": "x", "port": 80}]}).encode()

        seen = {}
        def opener(request, timeout):
            seen["auth"] = request.headers.get("Authorization")
            seen["timeout"] = timeout
            return Response()

        nodes = uf.fetch_source({"id": "p", "type": "api_token", "url": "https://example.test", "token": "secret"}, opener)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(seen["auth"], "Bearer secret")
        self.assertEqual(seen["timeout"], 30)

    def test_failed_refresh_does_not_replace_existing_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "snapshot.json")
            uf.write_snapshot([{"node_id": "old"}], path)
            with patch.object(uf, "fetch_source", side_effect=RuntimeError("offline")):
                result = uf.refresh_sources([{"id": "broken", "type": "profile_path", "path": "missing"}], dry_run=False)
            self.assertFalse(result["ok"])
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["nodes"][0]["node_id"], "old")

    def test_write_snapshot_is_atomic_result(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nested", "snapshot.json")
            self.assertEqual(uf.write_snapshot([{"node_id": "n1"}], path), path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["nodes"][0]["node_id"], "n1")


if __name__ == "__main__":
    unittest.main()
