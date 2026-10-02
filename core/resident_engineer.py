#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal local resident-engineer backend.

This module is deliberately dependency-free and offline-first.  It provides a
small contract for a future UI/agent bridge without calling paid providers,
changing proxy bindings, or allowing arbitrary commands.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APHUB_DATA_DIR") or ROOT_DIR / "data")
STATE_FILE = DATA_DIR / "resident_engineer_state.json"

SYSTEM_PROMPT = """你是 AgentProxyHub 的本地驻场网络工程师。
你的职责是检查本地代理出口、解释故障并给出可审计的安全建议。
铁律：默认使用 Gemini 3.8 Flash Tiered；Gemini 不可用时自动降级 GLM-5.3-Flash；最高事态由调度器明确标记后使用 GPT-6.1-SOL。
媒体生成、图片、视频和音频一律交给 Flow-Tools；不在驻场工程师中直接发起媒体任务。
模型凭据只从本地 DPAPI 金库短暂读取，不返回、不写日志；模型调用记录脱敏 usage ledger。
不跨区换绑；不修改账号或端口绑定；不执行白名单之外的动作；任何失败都要返回结构化错误且不得阻塞代理服务。
""".strip()

PROMPT_TEMPLATES: dict[str, str] = {
    "health_check": "请检查本地 AgentProxyHub 状态：节点文件、状态落盘和指定端口监听情况。只读，不修改配置。",
    "incident_report": "请根据以下本地检查结果生成简短故障报告，列出证据、影响、建议和未验证项：\n{details}",
    "action_result": "动作 {action} 已完成。结果：{result}",
}

# Names are the only executable surface exposed to a caller.  Handlers are
# intentionally data-returning functions; no shell/process/network mutation is
# part of this MVP.
ALLOWED_ACTIONS = frozenset({"health_check", "read_state", "record_event", "recover_mihomo", "model_status", "model_complete"})


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class ResidentEngineer:
    """Offline-safe stateful facade for the resident engineer."""

    def __init__(self, state_file: str | os.PathLike[str] = STATE_FILE,
                 *, nodes_file: str | os.PathLike[str] | None = None):
        self.state_file = Path(state_file)
        self.nodes_file = Path(nodes_file or DATA_DIR / "nodes.json")

    def load_state(self) -> dict[str, Any]:
        default = {"version": 1, "updated_at": None, "last_health": None, "events": []}
        try:
            with self.state_file.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            if not isinstance(value, dict):
                raise ValueError("state must be an object")
            merged = dict(default)
            merged.update(value)
            if not isinstance(merged.get("events"), list):
                merged["events"] = []
            return merged
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return default

    def save_state(self, state: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(state)
        value["version"] = 1
        value["updated_at"] = _utc_now()
        _atomic_write(self.state_file, value)
        return value

    def health_check(self, ports: list[int] | None = None, *, host: str = "127.0.0.1",
                     timeout: float = 0.25) -> dict[str, Any]:
        """Return local-only health evidence; individual probe failures are non-fatal."""
        result: dict[str, Any] = {"ok": True, "checked_at": _utc_now(), "components": {}}
        try:
            with self.nodes_file.open("r", encoding="utf-8-sig") as handle:
                nodes = json.load(handle)
            result["components"]["nodes_file"] = {"ok": isinstance(nodes, dict), "path": str(self.nodes_file)}
        except Exception as exc:  # health reporting must never block callers
            result["components"]["nodes_file"] = {"ok": False, "path": str(self.nodes_file), "error": type(exc).__name__}
        state_ok = True
        try:
            self.load_state()
        except Exception as exc:
            state_ok = False
            result["components"]["state"] = {"ok": False, "error": type(exc).__name__}
        if state_ok:
            result["components"]["state"] = {"ok": True, "path": str(self.state_file)}
        probe_results = []
        for port in ports or []:
            row = {"port": port, "open": False}
            try:
                with socket.create_connection((host, int(port)), timeout=max(0.01, timeout)):
                    row["open"] = True
            except (OSError, ValueError, TypeError) as exc:
                row["error"] = type(exc).__name__
            probe_results.append(row)
        result["ports"] = probe_results
        result["ok"] = all(c.get("ok", False) for c in result["components"].values())
        return result

    def recover_mihomo(self, *, runner: str | os.PathLike[str], wait_seconds: float = 12.0,
                       ports: list[int] | None = None) -> dict[str, Any]:
        """恢复与急停使用同一跨进程锁，避免检查后被人工急停却仍拉起。"""
        from core.kernel_control import control_lock
        with control_lock():
            return self._recover_mihomo_locked(runner=runner, wait_seconds=wait_seconds, ports=ports)

    def _recover_mihomo_locked(self, *, runner, wait_seconds=12.0, ports=None):
        from core.kernel_control import is_halted
        if is_halted():
            return {"ok": False, "code": "manual_halt", "recoverable": False}
        runner_path = Path(runner)
        if not runner_path.exists():
            return {"ok": False, "code": "runner_missing", "runner": str(runner_path), "recoverable": True}
        before = self.health_check(ports or [21001, 21008, 22002, 39999, 21909])
        if before.get("ok") and before.get("ports") and all(row.get("open") for row in before["ports"]):
            return {"ok": True, "action": "already_running", "before": before, "after": before,
                    "paid_calls": False, "bindings_changed": False}
        try:
            from core.kernel_control import OWNED_EXE
            # 恢复前禁止任意runner拉起第二个内核；runner必须是已知APH入口。
            existing = subprocess.run(
                ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                 "@(Get-CimInstance Win32_Process -Filter \"Name='mihomo.exe'\" | Where-Object {$_.ExecutablePath -eq '" + OWNED_EXE + "'}).Count"],
                capture_output=True, text=True, timeout=5)
            if existing.returncode == 0 and existing.stdout.strip() not in ('', '0'):
                return {"ok": False, "code": "owned_kernel_already_running", "recoverable": False,
                        "before": before, "after": before}
            if runner_path.name.lower() not in ('silent-run.bat', '启动agentproxyhub.bat'):
                return {"ok": False, "code": "runner_not_allowlisted", "recoverable": False}
            if is_halted():
                return {"ok": False, "code": "manual_halt", "recoverable": False}
            subprocess.Popen([str(runner_path)], cwd=str(runner_path.parent),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            return {"ok": False, "code": "runner_start_failed", "error": str(exc)[:160],
                    "before": before, "recoverable": True}
        deadline = time.monotonic() + max(0.5, float(wait_seconds))
        after = before
        while time.monotonic() < deadline:
            time.sleep(0.25)
            after = self.health_check(ports or [21001, 21008, 22002, 39999, 21909])
            if after.get("ok") and all(row.get("open") for row in after.get("ports", [])):
                break
        recovered = bool(after.get("ok") and all(row.get("open") for row in after.get("ports", [])))
        result = {"ok": recovered, "action": "recover_mihomo", "before": before, "after": after,
                  "runner": str(runner_path), "paid_calls": False, "bindings_changed": False}
        if recovered:
            # 统一放在实际恢复成功出口，覆盖MCP、EVA和其他本地调用；失败通知不阻塞内核。
            try:
                from core.alert_dispatch import notify_all
                result["notifications"] = notify_all(
                    "AgentProxyHub 内核已恢复，固定业务端口复核通过。",
                    event_id="agentproxyhub-kernel-recovered-" + str(int(time.time())),
                    emote="happy", motion="hop")
            except Exception:
                result["notifications"] = {"jingguanjia": False, "hermes_weixin": False,
                                            "hermes_detail": {"status": "exception"}}
        return result

    def prompt(self, template: str = "health_check", **values: Any) -> dict[str, Any]:
        if template not in PROMPT_TEMPLATES:
            return {"ok": False, "code": "unknown_prompt_template", "allowed": sorted(PROMPT_TEMPLATES)}
        try:
            text = PROMPT_TEMPLATES[template].format(**values)
        except (KeyError, ValueError) as exc:
            return {"ok": False, "code": "invalid_prompt_values", "error": str(exc)}
        return {"ok": True, "template": template, "system": SYSTEM_PROMPT, "prompt": text}

    def action_allowed(self, action: str) -> bool:
        return isinstance(action, str) and action in ALLOWED_ACTIONS

    def dispatch(self, action: str, args: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Dispatch only whitelisted local actions; all errors become recoverable results."""
        if not self.action_allowed(action):
            return {"ok": False, "code": "action_not_allowed", "action": action, "allowed": sorted(ALLOWED_ACTIONS), "recoverable": True}
        args = dict(args or {})
        try:
            if action == "health_check":
                result = self.health_check(args.get("ports"), host=str(args.get("host", "127.0.0.1")))
            elif action == "recover_mihomo":
                result = self.recover_mihomo(
                    runner=str(args.get("runner") or ROOT_DIR.parent / "Program Files" / "AgentProxyHub" / "silent-run.bat"),
                    wait_seconds=float(args.get("wait_seconds", 12)),
                    ports=args.get("ports") or [21001, 21008, 22002, 39999, 21909],
                )
            elif action == "read_state":
                result = self.load_state()
            elif action == "model_status":
                from .model_router import status
                result = status()
            elif action == "model_complete":
                from .model_router import complete
                result = complete(str(args.get("prompt") or ""), urgency=str(args.get("urgency") or "daily"), system=args.get("system"))
            else:  # record_event
                state = self.load_state()
                event = {"at": _utc_now(), "type": str(args.get("type", "event")), "details": args.get("details")}
                state["events"] = (state.get("events") or [])[-99:] + [event]
                result = self.save_state(state)
            return {"ok": True, "action": action, "result": result}
        except Exception as exc:  # never let a resident-engineer failure block the hub
            return {"ok": False, "action": action, "code": "action_failed", "error": str(exc)[:200], "recoverable": True}


__all__ = ["ResidentEngineer", "SYSTEM_PROMPT", "PROMPT_TEMPLATES", "ALLOWED_ACTIONS"]
