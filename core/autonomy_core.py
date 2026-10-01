#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轻量自治核心：事件审计、开关状态、路由建议与下载安全闸。

本模块只维护本地自治状态，不启动服务、不改写 bindings.json，也不执行下载。
调用方可将 route() 的结果交给现有端口/节点调度器执行。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APHUB_DATA_DIR") or ROOT_DIR / "data")
EVENTS_FILE = DATA_DIR / "autonomy_events.jsonl"
STATE_FILE = DATA_DIR / "autonomy_state.json"
DEFAULT_RETENTION_DAYS = 7
_ALLOWED_SCHEMES = {"https"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _safe_id(value: Any) -> str:
    """返回可用于去重/日志的脱敏标识。"""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


class EventStore:
    """追加式本地事件记录，支持按时间清理和摘要统计。"""

    def __init__(self, path: str | os.PathLike[str] = EVENTS_FILE):
        self.path = Path(path)

    def append(self, event_type: str, payload: Mapping[str, Any] | None = None,
               *, severity: str = "info", dedupe_key: str | None = None,
               occurred_at: str | None = None) -> dict[str, Any]:
        if not event_type or any(ord(ch) < 32 for ch in event_type):
            raise ValueError("event_type must be a non-empty printable string")
        event = {
            "event_id": f"evt_{_safe_id(f'{event_type}:{occurred_at or utc_now()}:{os.urandom(8).hex()}')}",
            "occurred_at": occurred_at or utc_now(),
            "event_type": event_type,
            "severity": severity if severity in {"info", "notice", "action_required", "critical"} else "info",
            "dedupe_key": dedupe_key or event_type,
            "payload": dict(payload or {}),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        return event

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict) and _parse_time(value.get("occurred_at")):
                        rows.append(value)
                except json.JSONDecodeError:
                    continue
        return rows

    def cleanup(self, *, retention_days: int = DEFAULT_RETENTION_DAYS, now: str | None = None) -> int:
        if retention_days < 1:
            raise ValueError("retention_days must be >= 1")
        cutoff = (_parse_time(now) or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(days=retention_days)
        rows = self.read()
        kept = [row for row in rows if (_parse_time(row.get("occurred_at")) or cutoff) >= cutoff]
        removed = len(rows) - len(kept)
        if removed:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            with temp.open("w", encoding="utf-8") as handle:
                for row in kept:
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            os.replace(temp, self.path)
        return removed

    def summary(self, *, now: str | None = None, retention_days: int = DEFAULT_RETENTION_DAYS) -> dict[str, Any]:
        cutoff = (_parse_time(now) or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(days=retention_days)
        rows = [r for r in self.read() if (_parse_time(r.get("occurred_at")) or cutoff) >= cutoff]
        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for row in rows:
            by_type[row["event_type"]] = by_type.get(row["event_type"], 0) + 1
            by_severity[row["severity"]] = by_severity.get(row["severity"], 0) + 1
        return {"window_days": retention_days, "count": len(rows), "by_type": by_type, "by_severity": by_severity}


class AutonomyState:
    """小型开关状态账本，原子写入并保留版本号。"""

    DEFAULTS = {"enabled": False, "routing_enabled": False, "download_guard_enabled": True,
               "auto_rebind_enabled": False, "hermes_notify_enabled": True,
               "usage_logging_enabled": True}

    def __init__(self, path: str | os.PathLike[str] = STATE_FILE):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "updated_at": None, "switches": dict(self.DEFAULTS)}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            switches = dict(self.DEFAULTS)
            switches.update(value.get("switches") or {})
            return {"version": 1, "updated_at": value.get("updated_at"), "switches": switches}
        except (OSError, ValueError, TypeError):
            return {"version": 1, "updated_at": None, "switches": dict(self.DEFAULTS)}

    def set(self, **switches: bool) -> dict[str, Any]:
        unknown = set(switches) - set(self.DEFAULTS)
        if unknown:
            raise ValueError(f"unknown switch: {sorted(unknown)[0]}")
        current = self.load()
        current["switches"].update({key: bool(value) for key, value in switches.items()})
        current["updated_at"] = utc_now()
        _atomic_json(self.path, current)
        return current


class RoutePolicy:
    """只做安全路由建议：优先同国家、健康且未 veto 的节点。"""

    def __init__(self, state: AutonomyState | None = None):
        self.state = state or AutonomyState()

    def route(self, candidates: Iterable[Mapping[str, Any]], *, country: str = "") -> dict[str, Any]:
        if not self.state.load()["switches"]["routing_enabled"]:
            return {"ok": False, "reason": "routing_disabled", "candidate": None}
        wanted = country.upper().strip()
        available = [dict(c) for c in candidates if c.get("port") and not c.get("vetoed") and c.get("health", "UNKNOWN") not in {"DOWN", "FAIL"}]
        if wanted:
            same = [c for c in available if str(c.get("country") or c.get("countryCode") or "").upper() == wanted]
            available = same or available
        available.sort(key=lambda c: (c.get("country") != wanted, -(float(c.get("score") or c.get("confidence") or 0))))
        return {"ok": bool(available), "reason": "selected" if available else "no_candidate", "candidate": available[0] if available else None}


class DownloadGuard:
    """下载保护：仅允许 HTTPS、限制大小，并阻止路径逃逸；不执行网络请求。"""

    def __init__(self, *, max_bytes: int = 512 * 1024 * 1024, output_dir: str | os.PathLike[str] | None = None):
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self.output_dir = Path(output_dir or DATA_DIR / "downloads").resolve()

    def validate(self, url: str, destination: str | os.PathLike[str], *, content_length: int | None = None) -> dict[str, Any]:
        parsed = urlsplit(url)
        target = Path(destination).resolve()
        try:
            target.relative_to(self.output_dir)
        except ValueError:
            return {"ok": False, "reason": "destination_outside_download_dir"}
        if parsed.scheme.lower() not in _ALLOWED_SCHEMES or not parsed.hostname:
            return {"ok": False, "reason": "https_required"}
        if content_length is not None and (content_length < 0 or content_length > self.max_bytes):
            return {"ok": False, "reason": "size_limit_exceeded"}
        return {"ok": True, "url_host": parsed.hostname.lower(), "destination": str(target), "max_bytes": self.max_bytes}
