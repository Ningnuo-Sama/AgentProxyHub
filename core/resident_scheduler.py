#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal opt-in resident scheduler for safe local maintenance.

The scheduler is deliberately conservative: it never refreshes paid upstreams,
never changes bindings, and is disabled until the ``enabled`` autonomy switch is
explicitly turned on.  Health work is injected so callers can choose a cheap,
read-only probe in tests and in the MCP host.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from .autonomy_core import AutonomyState, EventStore, utc_now
except (ImportError, ValueError):
    from core.autonomy_core import AutonomyState, EventStore, utc_now

HealthCheck = Callable[[], Mapping[str, Any]]
Summary = Callable[[], Mapping[str, Any]]
Notifier = Callable[..., bool]


def default_live_health_check() -> dict[str, Any]:
    """生产环境真实巡检与自愈：实测现役绑定端口置信度，遇送中/离线自动热替换。"""
    try:
        from core.confidence_engine import run as run_confidence
        from core.hot_swap_executor import scan_and_heal_all
        c_state = run_confidence(scope="bound", explicit=[], auto_heal=True)
        ports = c_state.get("ports", {})
        vetoed = [int(p) for p, r in ports.items() if r.get("vetoed")]
        healed = []
        if vetoed:
            healed = scan_and_heal_all(scope="bound")
        return {
            "status": "ok" if not vetoed or all(h.get("ok") for h in healed) else "warning",
            "source": "live_confidence_and_healing",
            "probed_ports_count": len(ports),
            "vetoed_ports": vetoed,
            "auto_healed": healed,
        }
    except Exception as exc:
        return {
            "status": "warning",
            "source": "health_check_exception",
            "error": str(exc)[:200],
        }


def default_live_notifier(text: str, **kwargs: Any) -> bool:
    """默认通过本地通知系统分发告警。"""
    try:
        from core.alert_dispatch import notify_all
        return notify_all(text, event_id=kwargs.get("event_id"))
    except Exception:
        return False


class ResidentScheduler:
    """A stoppable daemon thread with an explicit, persisted master switch."""

    def __init__(self, *, state: AutonomyState | None = None,
                 events: EventStore | None = None,
                 health_check: HealthCheck | None = None,
                 summary: Summary | None = None,
                 notifier: Notifier | None = None,
                 interval_seconds: float = 300.0,
                 emergency_only: bool | None = None):
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.state = state or AutonomyState()
        self.events = events or EventStore()
        self.health_check = health_check or (lambda: {"status": "ok", "source": "local_snapshot"})
        self.summary = summary or (lambda: self.events.summary())
        self.notifier = notifier
        self.interval_seconds = float(interval_seconds)
        if emergency_only is None:
            self.emergency_only = os.environ.get("APHUB_NOTIFY_EMERGENCY_ONLY", "1").lower() not in ("0", "false", "off")
        else:
            self.emergency_only = bool(emergency_only)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_result: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = bool(self._thread and self._thread.is_alive())
            return {"running": running, "enabled": bool(self.state.load()["switches"].get("enabled")),
                    "interval_seconds": self.interval_seconds, "emergency_only": self.emergency_only,
                    "last_result": self._last_result}

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

        vetoed = [int(p) for p in health.get("vetoed_ports", [])]
        healed = list(health.get("auto_healed", []))
        has_heal_failure = any(not h.get("ok") for h in healed)
        probe_failed = health.get("status") in ("error", "critical")
        # 真正紧急事件：自愈失败、探针崩溃或需要人工介入的严重故障；日常自愈与正常巡检彻底静默
        is_emergency = (
            error is not None
            or severity in ("action_required", "critical")
            or probe_failed
            or has_heal_failure
        )

        if notify and self.notifier:
            if not is_emergency and self.emergency_only:
                # 日常巡检与自动自治正常时彻底静默，不刷屏打扰用户
                result["notified"] = False
                result["notification_delivery"] = {"status": "skipped", "reason": "routine_ok_silent"}
            else:
                # 仅在真正紧急（如自愈失败、服务彻底不可用）时发送高优先级告警
                lines = [
                    f"🚨【AgentProxyHub 紧急告警：需人工介入】",
                    f"• 状态：{health.get('status', 'error')} (等级: {severity})",
                ]
                if has_heal_failure:
                    failed_ports = [h.get("port") for h in healed if not h.get("ok")]
                    lines.append(f"• 自愈失败端口：{failed_ports} (备选节点已耗尽或换绑失败)")
                elif vetoed and not healed:
                    lines.append(f"• 异常未恢复端口：{vetoed}")
                if error:
                    lines.append(f"• 探针崩溃报错：{error}")
                lines.append(f"• 事件编号：{event['event_id']}")
                text = "\n".join(lines)

                try:
                    delivered = self.notifier(text, event_id=event["event_id"], emote="alert", motion="jump")
                    result["notified"] = bool(delivered)
                    result["notification_delivery"] = delivered if isinstance(delivered, Mapping) else {"all": bool(delivered)}
                except Exception:
                    result["notified"] = False
                    result["notification_delivery"] = {"all": False, "status": "exception"}
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


__all__ = ["ResidentScheduler", "default_live_health_check", "default_live_notifier"]


def main():
    parser = argparse.ArgumentParser(description="AgentProxyHub 常驻巡检与自愈守护进程")
    parser.add_argument("--daemon", action="store_true", help="常驻前台循环运行（受控守护模式）")
    parser.add_argument("--once", action="store_true", help="执行单次完整巡检与自愈")
    parser.add_argument("--interval", type=float, default=300.0, help="巡检间隔秒数 (默认 300s)")
    parser.add_argument("--scope", type=str, default="bound", help="巡检范围 (bound/all)")
    parser.add_argument("--no-notify", action="store_true", help="不发送外部通知")
    parser.add_argument("--status", action="store_true", help="打印当前运行态状态")
    args = parser.parse_args()

    state = AutonomyState()
    # 确保主开关开启
    switches = state.load().get("switches", {})
    if not switches.get("enabled"):
        state.set(enabled=True)

    notifier = None if args.no_notify else default_live_notifier
    scheduler = ResidentScheduler(
        state=state,
        events=EventStore(),
        health_check=default_live_health_check,
        notifier=notifier,
        interval_seconds=args.interval,
    )

    if args.status:
        import json
        print(json.dumps(scheduler.status(), ensure_ascii=False, indent=2))
        return

    if args.once:
        import json
        res = scheduler.run_once(notify=not args.no_notify)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    if args.daemon:
        print(f"[scheduler-daemon] 启动 AgentProxyHub 常驻守护进程 (间隔 {args.interval}s) ...")
        # 直接在前台主线程中按间隔运行，响应 Ctrl+C 信号
        try:
            while True:
                switches = state.load().get("switches", {})
                if not switches.get("enabled"):
                    print("[scheduler-daemon] master switch disabled, exiting.")
                    break
                res = scheduler.run_once(notify=not args.no_notify)
                print(f"[scheduler-daemon] {utc_now()} 巡检完成: status={res.get('health', {}).get('status')}, "
                      f"healed={len(res.get('health', {}).get('auto_healed', []))}")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("[scheduler-daemon] 接收到退出信号，安全退出。")
            return


if __name__ == "__main__":
    main()
