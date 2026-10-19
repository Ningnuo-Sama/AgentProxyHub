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
BINDINGS_FILE = DATA_DIR / "bindings.json"
# 只读、几百字节、不含凭据；用于实测端口真实出口
EXIT_PROBE_URL = "http://ip-api.com/json/?fields=status,country,countryCode,query,isp,hosting"

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
ALLOWED_ACTIONS = frozenset({"health_check", "read_state", "record_event", "recover_mihomo",
                             "model_status", "model_complete", "verify_exit"})


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
                 *, nodes_file: str | os.PathLike[str] | None = None,
                 bindings_file: str | os.PathLike[str] | None = None):
        self.state_file = Path(state_file)
        self.nodes_file = Path(nodes_file or DATA_DIR / "nodes.json")
        self.bindings_file = Path(bindings_file or BINDINGS_FILE)

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

    def _append_event(self, event_type: str, details: Mapping[str, Any]) -> None:
        """巡检落盘：失败绝不阻塞调用方。"""
        try:
            state = self.load_state()
            state["events"] = (state.get("events") or [])[-99:] + [
                {"at": _utc_now(), "type": event_type, "details": dict(details)}
            ]
            self.save_state(state)
        except Exception:
            pass

    def load_bindings(self) -> dict[str, Any]:
        """读端口契约账本；读不到就当空账本，绝不抛。"""
        try:
            with self.bindings_file.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def probe_exit(self, port: int, timeout: float = 8.0) -> dict[str, Any]:
        """穿透本地端口实测真实出口；只读、无凭据、几百字节。"""
        row: dict[str, Any] = {"port": int(port), "ok": False}
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            proc = subprocess.run(
                ["curl.exe", "-s", "--max-time", str(int(timeout)),
                 "-x", f"socks5h://127.0.0.1:{int(port)}", EXIT_PROBE_URL],
                capture_output=True, text=True, timeout=timeout + 4,
                startupinfo=si, creationflags=0x08000000)
            raw = (proc.stdout or "").strip()
            if not raw:
                row["error"] = "empty_response"
                return row
            data = json.loads(raw)
            row.update({
                "ok": data.get("status") == "success",
                "ip": data.get("query"),
                "country": data.get("country"),
                "countryCode": data.get("countryCode"),
                "isp": data.get("isp"),
                "hosting": data.get("hosting"),
            })
            if not row["ok"]:
                row["error"] = "probe_status_not_success"
        except (OSError, ValueError, TypeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            row["error"] = type(exc).__name__
        return row

    def verify_exit(self, ports: list[int] | None = None, *, record: bool = True) -> dict[str, Any]:
        """按账本契约断言出口国家/IP；不符即记为 drift 事件。"""
        bindings = self.load_bindings()
        if ports:
            targets = [int(p) for p in ports]
        else:
            targets = sorted(int(k) for k in bindings if str(k).isdigit())
        rows: list[dict[str, Any]] = []
        drift: list[dict[str, Any]] = []
        for port in targets:
            contract = bindings.get(str(port)) or {}
            want_country = str(contract.get("expectedCountry") or "").upper()
            want_ip = str(contract.get("expectedIp") or "")
            seen = self.probe_exit(port)
            country_ok = bool(want_country) and seen.get("countryCode") == want_country
            ip_ok = (not want_ip) or seen.get("ip") == want_ip
            match = bool(seen.get("ok")) and country_ok and ip_ok
            row = {
                "port": port,
                "profile": contract.get("profile"),
                "expectedCountry": want_country or None,
                "expectedIp": want_ip or None,
                "actual": {k: seen.get(k) for k in ("ip", "country", "countryCode", "isp", "hosting")},
                "match": match,
            }
            if not match:
                row["drift"] = ("probe_failed" if not seen.get("ok")
                                else ("country" if not country_ok else "ip"))
                drift.append(row)
            rows.append(row)
        result = {"ok": not drift, "checked_at": _utc_now(),
                  "contracts_checked": len(rows), "ports": rows, "drift": drift}
        if record:
            self._append_event(
                "exit_verify_ok" if not drift else "exit_verify_drift",
                {"contracts_checked": len(rows),
                 "drift_ports": [d.get("port") for d in drift]})
        return result

    def health_check(self, ports: list[int] | None = None, *, host: str = "127.0.0.1",
                     timeout: float = 0.25, record: bool = False,
                     verify_exit: bool = False) -> dict[str, Any]:
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
        if verify_exit:
            exit_report = self.verify_exit(record=False)
            result["exit"] = exit_report
            result["ok"] = result["ok"] and bool(exit_report.get("ok"))
        if record:
            # 巡检必须落盘，否则"这几天的报告"永远是空的
            self._append_event("health_check", {
                "ok": result["ok"],
                "ports_open": [row["port"] for row in probe_results if row.get("open")],
                "ports_closed": [row["port"] for row in probe_results if not row.get("open")],
                "components_ok": all(c.get("ok", False) for c in result["components"].values()),
                "exit_drift": [row.get("port") for row in (result.get("exit") or {}).get("drift", [])]
                              if verify_exit else None,
            })
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
            # 黑窗治理 (2026-10-12)：全部子进程强制无窗口
            _si = subprocess.STARTUPINFO()
            _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            _si.wShowWindow = 0
            _hidden = {"startupinfo": _si, "creationflags": 0x08000000}
            # 恢复前禁止任意runner拉起第二个内核；runner必须是已知APH入口。
            existing = subprocess.run(
                ['powershell.exe', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command',
                 "@(Get-CimInstance Win32_Process -Filter \"Name='mihomo.exe'\" | Where-Object {$_.ExecutablePath -eq '" + OWNED_EXE + "'}).Count"],
                capture_output=True, text=True, timeout=5, **_hidden)
            if existing.returncode == 0 and existing.stdout.strip() not in ('', '0'):
                return {"ok": False, "code": "owned_kernel_already_running", "recoverable": False,
                        "before": before, "after": before}
            if runner_path.name.lower() not in ('silent-run.bat', '启动agentproxyhub.bat'):
                return {"ok": False, "code": "runner_not_allowlisted", "recoverable": False}
            if is_halted():
                return {"ok": False, "code": "manual_halt", "recoverable": False}
            subprocess.Popen([str(runner_path)], cwd=str(runner_path.parent), **_hidden)
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
        # 真实修复动作必须落账，供 EVA 全栈拓扑修復記錄与审计回溯。
        try:
            state = self.load_state()
            state["events"] = (state.get("events") or [])[-99:] + [{
                "at": _utc_now(), "type": "recover_mihomo_ok" if recovered else "recover_mihomo_failed",
                "details": {"ports_checked": [row.get("port") for row in after.get("ports", [])],
                            "already_running": bool(existing and existing.returncode == 0 and existing.stdout.strip() not in ('', '0'))},
            }]
            self.save_state(state)
        except Exception:
            pass
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
                result = self.health_check(
                    args.get("ports"),
                    host=str(args.get("host", "127.0.0.1")),
                    record=True,
                    verify_exit=bool(args.get("verify_exit", False)),
                )
            elif action == "verify_exit":
                result = self.verify_exit(args.get("ports"), record=True)
            elif action == "recover_mihomo":
                result = self.recover_mihomo(
                    runner=str(args.get("runner") or Path(ROOT_DIR.anchor) / "Program Files" / "AgentProxyHub" / "silent-run.bat"),
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
