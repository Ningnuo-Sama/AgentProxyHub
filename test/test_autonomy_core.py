#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.autonomy_core import AutonomyState, DownloadGuard, EventStore, RoutePolicy


class AutonomyCoreTests(unittest.TestCase):
    def test_event_cleanup_and_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            store = EventStore(Path(folder) / "events.jsonl")
            now = datetime.now(timezone.utc)
            store.append("fresh", {"port": 21001}, occurred_at=now.isoformat())
            store.append("old", occurred_at=(now - timedelta(days=8)).isoformat())
            self.assertEqual(store.cleanup(now=now.isoformat()), 1)
            self.assertEqual(store.summary(now=now.isoformat())["by_type"], {"fresh": 1})

    def test_switches_route_and_download_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            state = AutonomyState(Path(folder) / "state.json")
            self.assertFalse(state.load()["switches"]["routing_enabled"])
            state.set(enabled=True, routing_enabled=True)
            result = RoutePolicy(state).route([{"port": 21001, "country": "US", "score": 90}], country="US")
            self.assertTrue(result["ok"])
            guard = DownloadGuard(output_dir=Path(folder) / "downloads", max_bytes=10)
            self.assertTrue(guard.validate("https://example.test/file", Path(folder) / "downloads" / "file")["ok"])
            self.assertFalse(guard.validate("http://example.test/file", Path(folder) / "downloads" / "file")["ok"])
            self.assertFalse(guard.validate("https://example.test/file", Path(folder) / "downloads" / "file", content_length=11)["ok"])
            self.assertFalse(guard.validate("https://example.test/file", Path(folder) / "other" / "file")["ok"])


if __name__ == "__main__":
    unittest.main()
