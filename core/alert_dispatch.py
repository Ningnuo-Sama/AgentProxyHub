"""Best-effort multi-channel alert dispatch; payloads contain no credentials."""
from __future__ import annotations
import os
import subprocess
from typing import Any
from pathlib import Path
from .jingguanjia_notify import notify_jingguanjia


def notify_all(text: str, *, event_id: str | None = None, emote: str = "work", motion: str = "wiggle") -> dict[str, Any]:
    result: dict[str, Any] = {"jingguanjia": False, "hermes_weixin": False}
    try:
        result["jingguanjia"] = bool(notify_jingguanjia(text, event_id=event_id, emote=emote, motion=motion))
    except Exception:
        pass
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
                result["hermes_weixin"] = completed.returncode == 0
            except (OSError, subprocess.SubprocessError):
                pass
    return result

__all__ = ["notify_all"]
