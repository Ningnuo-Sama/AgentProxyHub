#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 子进程"绝对静默"工具（黑窗治理统一入口）。

背景（2026-10-12 黑窗根因）：
    本机把 Windows Terminal 设为默认控制台宿主，任何未显式隐藏的控制台子进程
    （curl.exe / cmd.exe / powershell.exe / hermes.exe ...）都会创建一个
    可见的 CASCADIA_HOSTING_WINDOW_CLASS 窗口 → 屏幕上"黑窗一闪"。

    单靠 subprocess 的 creationflags=CREATE_NO_WINDOW 在部分路径下并不足够，
    必须同时给出 STARTUPINFO 的 STARTF_USESHOWWINDOW + SW_HIDE，双保险。

用法：
    from core import winhide
    winhide.run(["curl.exe", ...], capture_output=True, text=True, timeout=10)
    winhide.popen([exe], stdout=DEVNULL)
    # 或就地合并参数
    subprocess.run(cmd, **winhide.hidden_kwargs(), timeout=5)
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any, Dict, Sequence

__all__ = ["hidden_kwargs", "run", "popen", "call", "CREATE_NO_WINDOW"]

CREATE_NO_WINDOW = 0x08000000


def hidden_kwargs() -> Dict[str, Any]:
    """返回让子进程"完全无窗口"所需的 subprocess 关键字参数。

    非 Windows 平台返回空 dict，保证跨平台调用安全。
    """
    if sys.platform != "win32":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    flags = CREATE_NO_WINDOW
    # 若父进程本身没有控制台，DETACHED_PROCESS 会进一步避免任何控制台宿主被创建
    if not _has_console():
        flags |= 0x00000008  # DETACHED_PROCESS
    return {"startupinfo": si, "creationflags": flags}


def _has_console() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except Exception:
        return True


def run(cmd: Sequence[str], **kwargs: Any):
    """subprocess.run 的静默包装：调用方参数优先，隐藏参数兜底。"""
    merged = dict(hidden_kwargs())
    merged.update(kwargs)
    return subprocess.run(cmd, **merged)


def popen(cmd: Sequence[str], **kwargs: Any):
    """subprocess.Popen 的静默包装。"""
    merged = dict(hidden_kwargs())
    merged.update(kwargs)
    return subprocess.Popen(cmd, **merged)


def call(cmd: Sequence[str], **kwargs: Any) -> int:
    """subprocess.call 的静默包装。"""
    merged = dict(hidden_kwargs())
    merged.update(kwargs)
    return subprocess.call(cmd, **merged)
