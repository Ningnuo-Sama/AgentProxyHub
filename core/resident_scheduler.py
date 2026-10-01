#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal opt-in resident scheduler for safe local maintenance.

The scheduler is deliberately conservative: it never refreshes paid upstreams,
never changes bindings, and is disabled until the ``enabled`` autonomy switch is
explicitly turned on.  Health work is injected so callers can choose a cheap,
read-only probe in tests and in the MCP host.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping

from .autonomy_core import AutonomyState, EventStore, utc_now

HealthCheck = Callable[[], Mapping[str, Any]]
Summary = Callable[[], Mapping[str, Any]]
Notifier = Callable[..., bool]


class ResidentScheduler:
    """A stoppable daemon thread with an explicit, persisted master switch."""

    def __init__(self, *, state: AutonomyState | None = None,
                 events: EventStore | None = None,
                 health_check: HealthCheck | None = None,
                 summary: Summary | None = None,
                 notifier: Notifier | None = None,
                 interval_seconds: float = 300.0):
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.state = state or AutonomyState()
        self.events = events or EventStore()
        self.health_check = health_check or (lambda: {"status": "ok", "source": "local_snapshot"})
        self.summary = summary or (lambda: self.events.summary())
        self.notifier = notifier
        self.interval_seconds = float(interval_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_result: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = bool(self._thread and self._thread.is_alive())
            return {"running": running, "enabled": bool(self.state.load()["switches"].get("enabled")),
                    "interval_seconds": self.interval_seconds, "last_result": self._last_result}

    def run_once(self, *, notify: bool = True) -> dict[str, Any]:
        """Run one read-only health pass; exceptions become auditable events."""
        started = time.monotonic()
        try:
            health = dict(self.health_check() or {})
            event_type = "scheduler.health_check"
            severity = "info" if health.get("status") in ("ok", "ready", "healthy") else "notice"
            error = None
        except Exception as exc:  # scheduler must survive a bad probe
            health = {"status": "error", "error": str(exc)[:200]}
            event_type, severity, error = "scheduler.health_check_error", "action_required", str(exc)[:200]
        summary = dict(self.summary() or {})
        event = self.events.append(event_type, {"health": health, "summary": summary}, severity=severity)
        result = {"ok": error is None, "health": health, "summary": summary,
                  "event_id": event["event_id"], "duration_ms": int((time.monotonic() - started) * 1000),
                  "paid_calls": False, "bindings_changed": False}
        if error:
            result["error"] = error
        if notify and self.notifier:
            text = f"AgentProxyHub 巡检：{health.get('status', 'unknown')}；事件 {summary.get('count', 0)} 条"
            try:
                result["notified"] = bool(self.notifier(text, event_id=event["event_id"], emote="work", motion="wiggle"))
            except Exception:
                result["notified"] = False
        with self._lock:
            self._last_result = result
        return result

    def start(self) -> dict[str, Any]:
        """Start only when the persisted master switch is enabled."""
        if not self.state.load()["switches"].get("enabled", False):
            return {"started": False, "reason": "disabled", **self.status()}
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"started": False, "reason": "already_running", **self.status()}
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="agentproxyhub-resident", daemon=True)
            self._thread.start()
        return {"started": True, **self.status()}

    def stop(self, timeout: float = 2.0) -> dict[str, Any]:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(max(0.0, timeout))
        return {"stopped": not (thread and thread.is_alive()), **self.status()}

    def _loop(self) -> None:
        while not self._stop.is_set():
            # Switches may be disabled by another process; stop promptly.
            if not self.state.load()["switches"].get("enabled", False):
                break
            self.run_once()
            self._stop.wait(self.interval_seconds)


__all__ = ["ResidentScheduler"]
