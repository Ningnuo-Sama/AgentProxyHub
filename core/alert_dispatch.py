"""Best-effort multi-channel alert dispatch; payloads contain no credentials."""
from __future__ import annotations
import json
import os
import subprocess
from typing import Any
from .jingguanjia_notify import notify_jingguanjia


def _hermes_result(completed: subprocess.CompletedProcess[str]) -> tuple[bool, dict[str, Any]]:
    """Require both a successful process exit and Hermes JSON success=true."""
    raw = (completed.stdout or completed.stderr or "").strip()
    detail: dict[str, Any] = {"returncode": completed.returncode}
    try:
        payload = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        payload = {}
    if isinstance(payload, dict):
        if payload.get("success") is True:
            detail["status"] = "sent"
            return completed.returncode == 0, detail
        error = payload.get("error") or payload.get("message")
        if error:
            detail["error"] = str(error)[:240]
    detail["status"] = "failed"
    return False, detail


def notify_all(text: str, *, event_id: str | None = None, emote: str = "work", motion: str = "wiggle") -> dict[str, Any]:
    result: dict[str, Any] = {"jingguanjia": False, "hermes_weixin": False}
    try:
        result["jingguanjia"] = bool(notify_jingguanjia(text, event_id=event_id, emote=emote, motion=motion))
    except Exception:
        result["jingguanjia_detail"] = {"status": "failed"}
    if os.environ.get("APHUB_HERMES_NOTIFY_ENABLED", "1").lower() not in {"0", "false", "off"}:
        exe = os.environ.get("APHUB_HERMES_EXE", r"D:\Program Files (x86)\hermes\bin\hermes.exe")
        target = os.environ.get("APHUB_HERMES_WEIXIN_TARGET", "weixin")
        # Hermes owns its own iLink login/config; the vault keeps related material indexed,
        # while this dispatcher deliberately never passes credential text on the CLI.
        if os.path.exists(exe):
            try:
                completed = subprocess.run([exe, "send", "--to", target, "--json", text[:2000]],
                                           capture_output=True, text=True, timeout=20,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
                sent, detail = _hermes_result(completed)
                result["hermes_weixin"] = sent
                result["hermes_detail"] = detail
            except (OSError, subprocess.SubprocessError):
                result["hermes_detail"] = {"status": "exception"}
        else:
            result["hermes_detail"] = {"status": "not_configured"}
    else:
        result["hermes_detail"] = {"status": "disabled"}
    return result


__all__ = ["notify_all"]
