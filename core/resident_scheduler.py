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
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DATA_DIR = Path(os.environ.get("APHUB_DATA_DIR") or _ROOT / "data")

try:
    from .autonomy_core import AutonomyState, EventStore, utc_now
except (ImportError, ValueError):
    from core.autonomy_core import AutonomyState, EventStore, utc_now

HealthCheck = Callable[[], Mapping[str, Any]]
Summary = Callable[[], Mapping[str, Any]]
Notifier = Callable[..., bool]


def l0_health_check() -> dict[str, Any]:
    """P2-4 生产默认巡检：L0 只读 13 项 + 契约守卫，**常态 0 WAN 字节、只报不改**。

    实现见 `core/ledger_watch.py`。本函数绝不触发 confidence 判国探测、
    绝不自愈、绝不改绑（用户契约 ⑥/⑩/⑪）。
    """
    try:
        from core.ledger_watch import collect, summary_line
    except ImportError:  # 脚本直跑
        from ledger_watch import collect, summary_line  # type: ignore
    report = collect(persist=True)
    events = list(report.get("events") or [])
    checks_failed = sorted(k for k, v in (report.get("checks") or {}).items() if not v.get("ok"))
    guards_failed = sorted(k for k, v in (report.get("guards") or {}).items()
                           if isinstance(v, dict) and v.get("ok") is False and not v.get("advisory"))
    has_action_required = any(e.get("severity") == "action_required" for e in events)
    status = "ok" if report.get("ok") else ("critical" if has_action_required or guards_failed else "warning")
    return {
        "status": status,
        "source": "l0_readonly_ledger_watch",
        "mode": "read_only",
        "wan_bytes": 0,
        "summary": summary_line(report),
        "checks_failed": checks_failed,
        "guards_failed": guards_failed,
        "events": events,
        "bound_ports": report.get("bound_ports"),
        "vetoed_ports": [e for e in checks_failed],  # 语义：需要人工看的项，不是「已否决端口」
        "auto_healed": [],
        "healing": "disabled_by_red_line",
        "report": report,
    }


def legacy_probing_health_check() -> dict[str, Any]:
    """历史实现：判国探测 + 自动热替换。**默认关闭**，仅 `APHUB_RESIDENT_ALLOW_PROBE=1` 时可用。

    ⚠️ 打开它会产生真实 WAN 流量并可能改绑（用户明令禁止）。保留仅为可回滚的历史路径。
    """
    if os.environ.get("APHUB_RESIDENT_ALLOW_PROBE", "0").lower() not in ("1", "true", "on"):
        return {"status": "warning", "source": "legacy_probing_disabled",
                "error": "APHUB_RESIDENT_ALLOW_PROBE!=1，历史探测路径被红线关闭"}
    if os.environ.get("APHUB_RESIDENT_ALLOW_HEAL", "0").lower() not in ("1", "true", "on"):
        return {"status": "warning", "source": "legacy_probing_readonly",
                "error": "只读模式：允许探测但禁止自愈（APHUB_RESIDENT_ALLOW_HEAL!=1）"}
    try:
        from core.confidence_engine import run as run_confidence
        from core.hot_swap_executor import scan_and_heal_all
        c_state = run_confidence(scope="bound", explicit=[], auto_heal=False)
        ports = c_state.get("ports", {})
        vetoed = [int(p) for p, r in ports.items() if r.get("vetoed")]
        healed = []
        if vetoed:
            healed = scan_and_heal_all(scope="bound")
        all_healed_ok = bool(healed) and all(h.get("ok") for h in healed)
        return {
            "status": "ok" if (not vetoed or all_healed_ok) else "warning",
            "source": "legacy_live_confidence_and_healing",
            "probed_ports_count": len(ports),
            "vetoed_ports": vetoed,
            "auto_healed": healed,
        }
    except Exception as exc:
        return {"status": "warning", "source": "health_check_exception", "error": str(exc)[:200]}


def default_live_notifier(text: str, **kwargs: Any) -> bool:
    """默认通知：走**双条件校验**的通道；两条都不通时落本地兜底文件（绝不丢告警）。"""
    try:
        from core.alert_dispatch import notify_or_fallback
        result = notify_or_fallback(text, event_id=kwargs.get("event_id"))
        return bool(result.get("jingguanjia")) or bool(result.get("hermes_weixin"))
    except Exception:
        return False


ACTION_LOG = DATA_DIR / "resident_action_log.jsonl"


def healing_permitted(state: "AutonomyState | None" = None) -> dict[str, Any]:
    """红线硬门禁（契约 ⑥）：任何自愈/换绑路径必须同时满足三个条件。"""
    autonomy = (state or AutonomyState()).load().get("switches", {})
    reasons: list[str] = []
    if not autonomy.get("auto_rebind_enabled"):
        reasons.append("auto_rebind_enabled=false")
    if os.environ.get("APHUB_RESIDENT_ALLOW_HEAL", "0").lower() not in ("1", "true", "on"):
        reasons.append("APHUB_RESIDENT_ALLOW_HEAL!=1")
    if os.environ.get("APHUB_RESIDENT_ALLOW_PROBE", "0").lower() not in ("1", "true", "on"):
        reasons.append("APHUB_RESIDENT_ALLOW_PROBE!=1")
    return {"permitted": not reasons, "blocked_by": reasons}


def _ledger_before_after() -> dict[str, Any]:
    """每次动作的 before/after 留痕（只摘要，不含密钥）。"""

    def digest(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        except OSError:
            return ""

    return {
        "bindings": digest(DATA_DIR / "bindings.json"),
        "config_yaml": digest(_ROOT / "config" / "config.yaml"),
        "autonomy_state": digest(DATA_DIR / "autonomy_state.json"),
        "l0_state": digest(DATA_DIR / "l0_state.json"),
    }


def _strip_report(health: Mapping[str, Any]) -> dict[str, Any]:
    """事件账本只留摘要；完整 L0 报告留在 data/l0_state.json 与 resident_action_log.jsonl。"""
    trimmed = {k: v for k, v in health.items() if k != "report"}
    report = health.get("report")
    if isinstance(report, Mapping):
        trimmed["report_summary"] = {
            "ok": report.get("ok"),
            "wan_bytes": report.get("wan_bytes"),
            "checked_at": report.get("checked_at"),
            "duration_ms": report.get("duration_ms"),
        }
    return trimmed


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

    # P2-33（2026-10-17 用户要求）：告警先经 Agent 总结成大白话再发。
    # 机器原文（L0-11 / G5_density / 事件 UUID）对用户不可读，直接推送等于转嫁阅读成本。
    _ALERT_SYSTEM = (
        "你是 AgentProxyHub 的驻场工程师，负责把代理池巡检告警翻译给非技术用户。"
        "要求：① 用简体中文大白话说清「哪里出了问题、严不严重、要不要动手」；"
        "② 禁止出现检查项编号（如 L0-11）、守卫代号（如 G5_density）、事件 UUID 等机器标识；"
        "③ 60 字以内，最多 3 行；④ 若只是需要人工确认但无实际危害，明说「暂不影响使用」；"
        "⑤ 只依据给定事实，不猜测、不编造端口或账号名。"
    )

    def _summarize_alert(self, machine_text: str, *, event_id: str) -> str | None:
        """把机器告警文案总结为大白话；任何失败都返回 None（调用方回落原文）。

        约束：只走 daily 档（近零流量）；失败**不提高频率、不重试**（用户契约）。
        """
        try:
            from .model_router import complete
            prompt = (
                "下面是代理池巡检的原始告警，请按系统要求总结：\n\n"
                f"{machine_text}"
            )
            result = complete(prompt, urgency="daily", system=self._ALERT_SYSTEM)
            if not result.get("ok"):
                return None
            text = (result.get("text") or result.get("content") or "").strip()
            if not text or len(text) > 400:
                return None
            return text
        except Exception:
            return None

    def run_once(self, *, notify: bool = True) -> dict[str, Any]:
        """Run one read-only health pass; exceptions become auditable events.

        P2-4：每次动作写 before/after，并强制记录 `paid_calls` 与 `bindings_changed`。
        """
        started = time.monotonic()
        before = _ledger_before_after()
        try:
            health = dict(self.health_check() or {})
            event_type = "scheduler.health_check"
            severity = "info" if health.get("status") in ("ok", "ready", "healthy") else (
                "action_required" if health.get("status") in ("critical", "error") else "notice")
            error = None
        except Exception as exc:  # scheduler must survive a bad probe
            health = {"status": "error", "error": str(exc)[:200]}
            event_type, severity, error = "scheduler.health_check_error", "action_required", str(exc)[:200]
        summary = dict(self.summary() or {})
        after = _ledger_before_after()
        bindings_changed = bool(before.get("bindings") and after.get("bindings")
                                and before["bindings"] != after["bindings"])
        attestation = {
            "before": before,
            "after": after,
            "paid_calls": False,
            "wan_bytes": int(health.get("wan_bytes") or 0),
            "bindings_changed": bindings_changed,
            "healing_permitted": healing_permitted(self.state),
            "mode": health.get("mode") or "read_only",
        }
        event = self.events.append(event_type, {"health": _strip_report(health), "summary": summary,
                                                "attestation": attestation}, severity=severity)
        result = {"ok": error is None, "health": health, "summary": summary,
                  "event_id": event["event_id"], "duration_ms": int((time.monotonic() - started) * 1000),
                  "attestation": attestation,
                  "paid_calls": False, "bindings_changed": bindings_changed}
        if error:
            result["error"] = error
        try:
            ACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
            with ACTION_LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "at": event["occurred_at"], "event_id": event["event_id"], "event_type": event_type,
                    "severity": severity, "duration_ms": result["duration_ms"],
                    "attestation": attestation,
                    "checks_failed": health.get("checks_failed"),
                    "guards_failed": health.get("guards_failed"),
                    "notified": None,
                }, ensure_ascii=False) + "\n")
        except OSError:
            result["action_log_write_failed"] = True

        vetoed = [str(p) for p in health.get("vetoed_ports", [])]
        healed = list(health.get("auto_healed", []))
        has_heal_failure = any(not h.get("ok") for h in healed)
        probe_failed = health.get("status") in ("error", "critical")
        # 真正紧急事件：契约违规 / 巡检崩溃 / 自愈失败；日常巡检彻底静默
        is_emergency = (
            error is not None
            or severity in ("action_required", "critical")
            or probe_failed
            or has_heal_failure
            or bool(health.get("guards_failed"))
        )

        if notify and self.notifier:
            if not is_emergency and self.emergency_only:
                # 日常巡检与自动自治正常时彻底静默，不刷屏打扰用户
                result["notified"] = False
                result["notification_delivery"] = {"status": "skipped", "reason": "routine_ok_silent"}
            else:
                # P2-33 件 1：**告警降频**。契约违规 / 基线超龄是持续状态而非一次性事件，
                # 5 分钟一轮会反复推送（用户原话「怎么一直报警」）。以问题指纹为键，
                # 同一指纹 24h 内只推一次；指纹变化或状态恢复后才再推。
                # fail-closed 友好：去重状态不可用时**允许推送**并显式标注，绝不静默吞。
                try:
                    from .alert_dedup import check_and_record as _dedup_check
                except ImportError:  # 脚本直跑
                    from alert_dedup import check_and_record as _dedup_check  # type: ignore
                dedup = _dedup_check(
                    checks_failed=health.get("checks_failed"),
                    guards_failed=health.get("guards_failed"),
                    severity=severity,
                    error_kind=(type(error).__name__ if error else None),
                    is_emergency=is_emergency,
                )
                result["alert_dedup"] = {k: v for k, v in dedup.items() if k != "note"}
                if not dedup.get("allowed"):
                    result["notified"] = False
                    result["notification_delivery"] = {"status": "suppressed",
                                                       "reason": dedup.get("reason"),
                                                       "fingerprint": dedup.get("fingerprint"),
                                                       "note": dedup.get("note")}
                    try:
                        ACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
                        with ACTION_LOG.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps({
                                "at": event["occurred_at"], "event_id": event["event_id"],
                                "event_type": "scheduler.alert_suppressed",
                                "severity": "info", "duration_ms": result["duration_ms"],
                                "attestation": attestation,
                                "checks_failed": health.get("checks_failed"),
                                "guards_failed": health.get("guards_failed"),
                                "notified": False,
                                "alert_dedup": {k: v for k, v in dedup.items() if k != "note"},
                            }, ensure_ascii=False) + "\n")
                    except OSError:
                        result["action_log_write_failed"] = True
                    with self._lock:
                        self._last_result = result
                    return result
                dedup_note = dedup.get("note")
                dedup_degraded = dedup.get("dedup_state") == "unavailable"

                # 仅在真正紧急（契约违规、服务彻底不可用）时发送高优先级告警
                # P2-33（2026-10-17 用户要求）：告警**先经 Agent 总结成大白话**再发，
                # 不把机器原文（检查项编号 / 事件 UUID）直接甩给用户。
                lines = [
                    f"🚨【AgentProxyHub 紧急告警：需人工介入】",
                    f"• 状态：{health.get('status', 'error')} (等级: {severity})",
                    f"• 模式：{health.get('mode', 'read_only')}  ｜  本轮 WAN 字节：{health.get('wan_bytes', 0)}",
                ]
                if has_heal_failure:
                    failed_ports = sorted(set(h.get("port") for h in healed if not h.get("ok") and h.get("port") is not None))
                    lines.append(f"• 自愈失败端口：{failed_ports} (备选节点已耗尽或换绑失败)")
                elif vetoed:
                    lines.append(f"• L0 异常检查项：{vetoed}")
                if health.get("guards_failed"):
                    lines.append(f"• 契约守卫违规：{health.get('guards_failed')}")
                if error:
                    lines.append(f"• 探针崩溃报错：{error}")
                lines.append(f"• 事件编号：{event['event_id']}")
                if dedup_degraded:
                    # 降滤器没生效 ⇒ 必须让用户看见，不能装作在降噪
                    lines.append(f"• 降滤状态：不可用（{dedup.get('state_reason')}），本轮未做去重")
                elif dedup_note:
                    lines.append(f"• 降滤说明：{dedup_note}")
                machine_text = "\n".join(lines)

                text = self._summarize_alert(machine_text, event_id=event["event_id"]) or machine_text

                try:
                    delivered = self.notifier(text, event_id=event["event_id"], emote="alert", motion="jump")
                    result["notified"] = bool(delivered)
                    result["notification_delivery"] = delivered if isinstance(delivered, Mapping) else {"all": bool(delivered)}
                    result["alert_text"] = text
                    result["alert_raw"] = machine_text
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


__all__ = ["ResidentScheduler", "l0_health_check", "legacy_probing_health_check",
           "healing_permitted", "default_live_notifier"]


def _ensure_streams() -> None:
    """pythonw.exe 下 sys.stdout/stderr 为 None，`print` 会抛异常把守护进程打死。

    这里把它们重定向到 `logs/resident-scheduler.log`（静默执行 + 留痕）。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_dir = _ROOT / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handle = open(log_dir / "resident-scheduler.log", "a", encoding="utf-8", buffering=1)
    except OSError:
        handle = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = handle
    if sys.stderr is None:
        sys.stderr = handle


def main():
    _ensure_streams()
    parser = argparse.ArgumentParser(description="AgentProxyHub 常驻巡检守护进程（L0 只读 · 0 字节 · 只报不改）")
    parser.add_argument("--daemon", action="store_true", help="常驻前台循环运行（受控守护模式）")
    parser.add_argument("--once", action="store_true", help="执行单次完整 L0 巡检")
    parser.add_argument("--interval", type=float, default=300.0, help="巡检间隔秒数 (默认 300s)")
    parser.add_argument("--scope", type=str, default="bound", help="巡检范围 (bound/all)［历史参数，L0 忽略］")
    parser.add_argument("--no-notify", action="store_true", help="不发送外部通知")
    parser.add_argument("--status", action="store_true", help="打印当前运行态状态")
    parser.add_argument("--allow-probe", action="store_true",
                        help="⚠️ 显式启用历史判国探测路径（会产生 WAN 流量；需 auto_rebind_enabled 同时为真才可自愈）")
    parser.add_argument("--json", action="store_true", help="以 JSON 打印结果")
    args, unknown = parser.parse_known_args()

    # 红线：--fix 永久禁止（用户契约 ⑥/⑪）。任何计划任务都不得带它。
    if "--fix" in unknown or any("--fix" in str(a) for a in unknown):
        print("[scheduler] 拒绝执行：--fix 属红线动作（自动换绑），已硬门禁阻断。", file=sys.stderr)
        return 2

    state = AutonomyState()
    switches = state.load().get("switches", {})

    if args.allow_probe:
        os.environ.setdefault("APHUB_RESIDENT_ALLOW_PROBE", "1")
    gate = healing_permitted(state)
    health_check = legacy_probing_health_check if args.allow_probe else l0_health_check

    if not switches.get("enabled") and (args.daemon or args.once):
        print("[scheduler] 提示：autonomy 总开关 enabled=false，本轮以只读巡检运行（不自愈、不改绑）。")

    notifier = None if args.no_notify else default_live_notifier
    scheduler = ResidentScheduler(
        state=state,
        events=EventStore(),
        health_check=health_check,
        notifier=notifier,
        interval_seconds=args.interval,
    )

    if args.status:
        print(json.dumps({"scheduler": scheduler.status(), "healing_gate": gate,
                          "mode": "legacy_probe" if args.allow_probe else "L0_readonly"},
                         ensure_ascii=False, indent=2))
        return 0

    if args.once:
        res = scheduler.run_once(notify=not args.no_notify)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            health = res.get("health") or {}
            print(f"[scheduler] {utc_now()} L0 巡检: status={health.get('status')} "
                  f"wan_bytes={health.get('wan_bytes', 0)} checks_failed={health.get('checks_failed')} "
                  f"guards_failed={health.get('guards_failed')}")
            print(f"[scheduler] 自愈门禁: {gate}")
            for event in health.get("events") or []:
                print(f"  [{event.get('severity')}] {event.get('type')}: "
                      f"{json.dumps(event.get('detail'), ensure_ascii=False)[:240]}")
        return 0 if res.get("ok") else 1

    if args.daemon:
        print(f"[scheduler-daemon] 启动 L0 只读常驻巡检 (间隔 {args.interval}s, 模式="
              f"{'legacy_probe' if args.allow_probe else 'L0_readonly'}, 自愈门禁={gate}) ...")
        try:
            while True:
                if not state.load().get("switches", {}).get("enabled"):
                    print("[scheduler-daemon] master switch disabled, exiting.")
                    break
                res = scheduler.run_once(notify=not args.no_notify)
                health = res.get("health") or {}
                print(f"[scheduler-daemon] {utc_now()} 巡检完成: status={health.get('status')} "
                      f"wan_bytes={health.get('wan_bytes', 0)} "
                      f"checks_failed={health.get('checks_failed')} guards_failed={health.get('guards_failed')}")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("[scheduler-daemon] 接收到退出信号，安全退出。")
            return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
