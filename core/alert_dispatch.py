"""Best-effort multi-channel alert dispatch; payloads contain no credentials.

P2-4（2026-10-17）告警**双条件**口径：
  * 鲸管家：先 `GET /health` 必须 **200**，再 `POST /notify` 必须 **202** 才算送达；
  * Hermes 微信：`gateway_state.json` 必须为 `running` **且** 微信平台为 `connected`，
    再执行 `hermes send --to weixin --json` 且返回 `success=true` 才算送达。
    **只看进程存活 / 只看平台名都不算在线。**
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from collections.abc import Mapping as Mapping_like

from .jingguanjia_notify import jingguanjia_healthy, notify_jingguanjia, notify_jingguanjia_verified

HERMES_HOME = Path(os.environ.get("APHUB_HERMES_HOME") or r"D:\Program Files (x86)\hermes")
HERMES_STATE = HERMES_HOME / "gateway_state.json"
HERMES_EXE_CANDIDATES = (
    os.environ.get("APHUB_HERMES_EXE") or "",
    str(HERMES_HOME / "bin" / "hermes.cmd"),
    str(HERMES_HOME / "hermes-agent" / "venv" / "Scripts" / "hermes.exe"),
)


def hermes_executable() -> str | None:
    for candidate in HERMES_EXE_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _hidden_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kwargs["startupinfo"] = si
    return kwargs


def hermes_gateway_state() -> dict[str, Any]:
    """读取 Hermes 网关状态（只读；不含任何凭据字段）。"""
    try:
        raw = json.loads(HERMES_STATE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return {"available": False, "error": type(exc).__name__, "path": str(HERMES_STATE)}
    platforms = raw.get("platforms") or {}
    weixin = (platforms.get("weixin") or {}) if isinstance(platforms, dict) else {}
    return {
        "available": True,
        "gateway_state": raw.get("gateway_state"),
        "exit_reason": raw.get("exit_reason"),
        "updated_at": raw.get("updated_at"),
        "code_version": raw.get("code_version"),
        "weixin_state": weixin.get("state"),
        "weixin_updated_at": weixin.get("updated_at"),
        "weixin_needs_attention": weixin.get("needs_attention"),
        "platforms": sorted(platforms.keys()) if isinstance(platforms, dict) else [],
    }


def hermes_online() -> dict[str, Any]:
    """双条件之一：`running` + 微信 `connected`。"""
    state = hermes_gateway_state()
    running = state.get("gateway_state") == "running"
    connected = state.get("weixin_state") == "connected"
    return {"ok": bool(running and connected), "gateway_running": running,
            "weixin_connected": connected, "state": state,
            "reason": None if (running and connected) else "gateway_state_condition_unmet"}


def hermes_send_verified(text: str, *, target: str | None = None, timeout: float = 25.0) -> dict[str, Any]:
    """双条件之二：`hermes send --json` 必须返回 `success=true`。"""
    exe = hermes_executable()
    if not exe:
        return {"ok": False, "channel": "hermes_weixin", "status": "not_configured",
                "searched": [c for c in HERMES_EXE_CANDIDATES if c]}
    gate = hermes_online()
    if not gate["ok"]:
        return {"ok": False, "channel": "hermes_weixin", "status": "gateway_not_online",
                "detail": {"gateway_running": gate["gateway_running"],
                           "weixin_connected": gate["weixin_connected"]}}
    payload_target = target or os.environ.get("APHUB_HERMES_WEIXIN_TARGET", "weixin")
    try:
        completed = subprocess.run([exe, "send", "--to", payload_target, "--json", str(text)[:2000]],
                                   capture_output=True, timeout=timeout, check=False, **_hidden_kwargs())
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "channel": "hermes_weixin", "status": "exception",
                "detail": {"error": type(exc).__name__}}
    raw = (completed.stdout or completed.stderr or b"")
    try:
        decoded = raw.decode("utf-8", "replace").strip()
    except (UnicodeDecodeError, AttributeError):
        decoded = str(raw)
    detail: dict[str, Any] = {"returncode": completed.returncode, "exe": exe}
    try:
        parsed = json.loads(decoded) if decoded else {}
    except (ValueError, TypeError):
        parsed = {}
    if isinstance(parsed, dict) and parsed.get("success") is True:
        detail["status"] = "sent"
        return {"ok": completed.returncode == 0, "channel": "hermes_weixin",
                "status": "sent", "detail": detail,
                "result": {k: v for k, v in parsed.items() if k not in {"token", "credentials"}}}
    detail["status"] = "failed"
    if isinstance(parsed, dict):
        error = parsed.get("error") or parsed.get("message")
        if error:
            detail["error"] = str(error)[:240]
    elif decoded:
        detail["error"] = decoded[:240]
    return {"ok": False, "channel": "hermes_weixin", "status": "failed", "detail": detail}


def channel_status() -> dict[str, Any]:
    """两个告警通道的**当前可用性**（供值班手册与自检使用）。"""
    jg_health = jingguanjia_healthy()
    hermes = hermes_online()
    return {
        "jingguanjia": {"health_200": bool(jg_health),
                        "endpoint": os.environ.get("JG_NOTIFY_HEALTH_URL", "http://127.0.0.1:8766/health"),
                        "notify_contract": "POST /notify == 202"},
        "hermes_weixin": {"online": hermes["ok"], "gateway_running": hermes["gateway_running"],
                          "weixin_connected": hermes["weixin_connected"],
                          "exe": hermes_executable(), "state_file": str(HERMES_STATE),
                          "state": hermes["state"]},
    }


def notify_all(text: str, *, event_id: str | None = None, emote: str = "work",
               motion: str = "wiggle", verified: bool = True) -> dict[str, Any]:
    """双通道分发。任一通道不可用时**如实返回不可用**，绝不伪报成功。"""
    result: dict[str, Any] = {"jingguanjia": False, "hermes_weixin": False}
    try:
        if verified:
            jg = notify_jingguanjia_verified(text, event_id=event_id, emote=emote, motion=motion)
            result["jingguanjia"] = bool(jg.get("ok"))
            result["jingguanjia_detail"] = jg
        else:
            result["jingguanjia"] = bool(notify_jingguanjia(text, event_id=event_id, emote=emote, motion=motion))
    except Exception:  # noqa: BLE001
        result["jingguanjia_detail"] = {"status": "exception"}

    if os.environ.get("APHUB_HERMES_NOTIFY_ENABLED", "1").lower() not in {"0", "false", "off"}:
        sent = hermes_send_verified(text)
        result["hermes_weixin"] = bool(sent.get("ok"))
        result["hermes_detail"] = sent.get("detail") or {"status": sent.get("status")}
    else:
        result["hermes_detail"] = {"status": "disabled"}
    return result


def undelivered_sink(text: str, *, event_id: str | None = None, reason: Mapping_like | None = None) -> dict[str, Any]:
    """两条通道都不可用时的**本地兜底**：落盘留痕，绝不丢告警、绝不伪报送达。"""
    data_dir = Path(os.environ.get("APHUB_DATA_DIR") or str(Path(__file__).resolve().parent.parent / "data"))
    target = data_dir / "alerts" / "undelivered.jsonl"
    record = {"at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
              "event_id": event_id, "text": str(text)[:2000], "reason": dict(reason or {})}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"ok": True, "sink": str(target)}
    except OSError as exc:
        return {"ok": False, "sink": str(target), "error": type(exc).__name__}


def notify_or_fallback(text: str, *, event_id: str | None = None, emote: str = "work",
                       motion: str = "wiggle") -> dict[str, Any]:
    """先走双条件通道；两条都不通则落本地兜底，并在返回值里显式标注 `channel_degraded`。"""
    result = notify_all(text, event_id=event_id, emote=emote, motion=motion)
    delivered = bool(result.get("jingguanjia")) or bool(result.get("hermes_weixin"))
    result["channel_degraded"] = not delivered
    if not delivered:
        result["fallback"] = undelivered_sink(text, event_id=event_id,
                                              reason={"jingguanjia": result.get("jingguanjia_detail"),
                                                      "hermes": result.get("hermes_detail")})
    return result


__all__ = ["notify_all", "notify_or_fallback", "undelivered_sink", "channel_status",
           "hermes_send_verified", "hermes_online", "hermes_gateway_state", "hermes_executable"]
