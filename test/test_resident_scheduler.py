#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

from core.autonomy_core import AutonomyState, EventStore
from core.resident_scheduler import ResidentScheduler


class ResidentSchedulerTests(unittest.TestCase):
    def make(self):
        folder = tempfile.TemporaryDirectory()
        state = AutonomyState(Path(folder.name) / "state.json")
        events = EventStore(Path(folder.name) / "events.jsonl")
        notifications = []
        scheduler = ResidentScheduler(
            state=state,
            events=events,
            health_check=lambda: {"status": "healthy", "port_open": 1},
            notifier=lambda text, **kwargs: notifications.append((text, kwargs)) or True,
            interval_seconds=0.02,
        )
        return folder, state, events, notifications, scheduler

    def test_disabled_by_default_and_start_stop(self):
        folder, state, events, notifications, scheduler = self.make()
        try:
            self.assertFalse(scheduler.start()["started"])
            state.set(enabled=True)
            self.assertTrue(scheduler.start()["started"])
            self.assertTrue(scheduler.status()["running"])
            result = scheduler.run_once()
            self.assertTrue(result["ok"])
            self.assertFalse(result["paid_calls"])
            self.assertFalse(result["bindings_changed"])
            # 2026-10-09 起 emergency_only 默认开启：日常健康巡检必须彻底静默
            self.assertFalse(result["notified"])
            self.assertFalse(notifications)
            self.assertEqual(
                result["notification_delivery"],
                {"status": "skipped", "reason": "routine_ok_silent"},
            )
            self.assertGreaterEqual(events.summary()["count"], 1)

            # 但真正紧急的事件（此处为探针崩溃）必须仍然触发高优先级告警
            def boom():
                raise RuntimeError("probe crashed")

            emergency = ResidentScheduler(
                state=state,
                events=EventStore(Path(folder.name) / "emergency.jsonl"),
                health_check=boom,
                notifier=lambda text, **kwargs: notifications.append((text, kwargs)) or True,
                interval_seconds=0.02,
            )
            emergency.run_once()
            self.assertTrue(notifications)
            self.assertTrue(scheduler.stop()["stopped"])
        finally:
            folder.cleanup()

    def test_disabling_switch_stops_next_loop(self):
        folder, state, events, notifications, scheduler = self.make()
        try:
            state.set(enabled=True)
            scheduler.start()
            state.set(enabled=False)
            scheduler._stop.wait(0.08)
            self.assertFalse(scheduler.status()["running"])
        finally:
            scheduler.stop()
            folder.cleanup()


if __name__ == "__main__":
    unittest.main()
