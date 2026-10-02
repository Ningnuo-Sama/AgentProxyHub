#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AgentProxyHub 最小控制状态账本。

状态仅描述后端能力开关，不包含 UI 状态或凭据；写入采用临时文件替换，
避免 MCP/巡检进程读取到半截 JSON。环境变量 APHUB_CONTROL_STATE_FILE
可将状态文件放到独立运行数据目录。
"""
import contextlib
import copy
import json
import os
import time
from typing import Any, Dict, Optional

try:
    import msvcrt
except ImportError:  # pragma: no cover - Linux 开发环境
    msvcrt = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("APHUB_DATA_DIR") or os.path.join(ROOT, "data")
STATE_FILE = os.environ.get("APHUB_CONTROL_STATE_FILE") or os.path.join(DATA_DIR, "control_state.json")
LOCK_FILE = STATE_FILE + ".lock"

DEFAULT_FLAGS = {
    "enabled": True,
    "proxy_auto_switch": False,
    "price_sync": False,
    "download_protection": True,
    "openviking_sink": False,
}
FLAG_NAMES = frozenset(DEFAULT_FLAGS)


def _default_state() -> Dict[str, Any]:
    return {"version": 1, "updated_at": 0, "updated_by": "default", "flags": dict(DEFAULT_FLAGS)}


def _normalize(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("控制状态必须是 JSON 对象")
    flags = value.get("flags")
    if not isinstance(flags, dict):
        flags = {}
    merged = dict(DEFAULT_FLAGS)
    for key, flag in flags.items():
        if key not in FLAG_NAMES:
            raise ValueError(f"未知控制开关: {key}")
        if not isinstance(flag, bool):
            raise ValueError(f"开关 {key} 必须是布尔值")
        merged[key] = flag
    return {
        "version": 1,
        "updated_at": int(value.get("updated_at") or 0),
        "updated_by": str(value.get("updated_by") or "unknown")[:80],
        "flags": merged,
    }


def _read_unlocked() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return _default_state()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as handle:
            return _normalize(json.load(handle))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"控制状态文件损坏或不可读: {exc}") from exc


@contextlib.contextmanager
def locked():
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(LOCK_FILE, "a+b") as lock:
        if msvcrt:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if msvcrt:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def read() -> Dict[str, Any]:
    with locked():
        return copy.deepcopy(_read_unlocked())


def update(patch: Dict[str, Any], updated_by: str = "mcp") -> Dict[str, Any]:
    if not isinstance(patch, dict):
        raise ValueError("patch 必须是 JSON 对象")
    unknown = set(patch) - FLAG_NAMES
    if unknown:
        raise ValueError(f"未知控制开关: {', '.join(sorted(unknown))}")
    if any(not isinstance(value, bool) for value in patch.values()):
        raise ValueError("所有控制开关值必须是布尔值")
    with locked():
        state = _read_unlocked()
        state["flags"].update(patch)
        state["updated_at"] = int(time.time())
        state["updated_by"] = str(updated_by or "mcp")[:80]
        temp = f"{STATE_FILE}.{os.getpid()}.tmp"
        with open(temp, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, STATE_FILE)
        return copy.deepcopy(state)
