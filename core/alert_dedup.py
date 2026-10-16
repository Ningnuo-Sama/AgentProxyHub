#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""告警去重 / 降频（P2-33 件 1）：同一问题指纹 24h 内只推一次。

## 为什么需要它
驻场调度器 5 分钟一轮，`is_emergency` 为真即推送。而契约违规（G4/G5/G16）与
L0-11 基线超龄是**持续状态**，不是一次性事件 ⇒ 用户原话「**怎么一直报警**」。

## 指纹定义（可审计、可复现）
fingerprint = sha256( sorted(checks_failed) + sorted(guards_failed) + severity + error_kind )

- **只收「问题身份」，不收数值**：端口集合 / 账号数 / 字节数都可能每轮微动，
  收进来会让指纹永远变化、降频完全失效。
- **指纹变化才允许再推**：新增或消除任一失败项 ⇒ 身份变了，必须让用户知道。
- **状态恢复 ok 后重置该指纹时间戳**：同一问题第二次出现时能立刻再报（不被 24h 挡住）。

## fail-closed 友好（红线：不得静默吞告警）
去重状态文件**缺失 / 损坏 / 不可写**时：
  → **当次允许推送**，并在返回里显式标注 `dedup_state="unavailable"` + `reason`，
    由调用方把该标注带进告警文案（用户看得到「降滤器没生效」），
    **绝不**因为读不到状态就静默跳过 —— 那正是「看着在守护其实没报」。
  唯一例外：写入失败但**读取成功**时，只影响「记录本次推送」，
  不影响本次放行决策（仍会推送，仅标注 `record_failed`）。

## 落点
`data/alert_dedup.json`（与 `bindings.json` 同目录，遵循 APHUB_DATA_DIR）。
原子写：唯一 tmp + `os.replace`；一行回滚 = 删该文件（缺失即退化为「每轮都推」）。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APHUB_DATA_DIR") or ROOT_DIR / "data")
DEDUP_FILE = DATA_DIR / "alert_dedup.json"

WINDOW_H = float(os.environ.get("APHUB_ALERT_DEDUP_WINDOW_H", "24"))
MAX_ENTRIES = int(os.environ.get("APHUB_ALERT_DEDUP_MAX_ENTRIES", "200"))


def _dedup_path() -> Path:
    """去重状态文件路径**动态解析**（导入后改 APHUB_DATA_DIR 也生效，便于隔离测试）。"""
    return Path(os.environ.get("APHUB_DATA_DIR") or DATA_DIR) / "alert_dedup.json"


def _now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


def _parse(ts: Any) -> dt.datetime | None:
    if not ts:
        return None
    try:
        return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def fingerprint_of(*, checks_failed: Iterable[str] | None = None,
                   guards_failed: Iterable[str] | None = None,
                   severity: str | None = None,
                   error_kind: str | None = None) -> str:
    """问题指纹：只由「问题身份」决定，**不含任何会每轮微动的数值**。"""
    parts = {
        "checks": sorted({str(x) for x in (checks_failed or [])}),
        "guards": sorted({str(x) for x in (guards_failed or [])}),
        "severity": str(severity or "").strip().lower(),
        "error_kind": str(error_kind or "").strip().lower()[:80],
    }
    canonical = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _read_state() -> tuple[dict[str, Any], dict[str, Any]]:
    """读去重状态。**永不抛异常**；返回 `(state, status)`。

    status: {present, valid, reason, path}
    """
    status: dict[str, Any] = {"path": str(_dedup_path()), "present": _dedup_path().exists(),
                              "valid": False, "reason": None}
    if not status["present"]:
        status["reason"] = "state_missing"
        return {}, status
    try:
        raw = json.loads(_dedup_path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        status["reason"] = "state_unreadable:%s" % type(exc).__name__
        return {}, status
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), dict):
        status["reason"] = "state_malformed"
        return {}, status
    status["valid"] = True
    return raw, status


def _prune(entries: Mapping[str, Any], now: dt.datetime) -> dict[str, Any]:
    """清理过期与超量条目，防止状态文件无限增长。"""
    kept: dict[str, Any] = {}
    for fp, rec in (entries or {}).items():
        if not isinstance(rec, dict):
            continue
        ts = _parse(rec.get("last_notified_at"))
        if ts is None:
            continue  # 无时间戳的条目不可判定，直接丢弃（fail-closed 方向是"允许再推"）
        if (now - ts).total_seconds() <= WINDOW_H * 3600:
            kept[str(fp)] = rec
    if len(kept) > MAX_ENTRIES:
        # 只保留最近的 MAX_ENTRIES 条
        ordered = sorted(kept.items(), key=lambda kv: str(kv[1].get("last_notified_at")), reverse=True)
        kept = dict(ordered[:MAX_ENTRIES])
    return kept


def _write_state(entries: Mapping[str, Any], now: dt.datetime) -> dict[str, Any]:
    """原子写。失败**不影响**放行决策，只影响记录（返回 ok=False 由调用方标注）。"""
    doc = {"version": 1, "updated_at": _iso(now), "window_hours": WINDOW_H,
           "note": "P2-33 告警去重状态：同一问题指纹在 window_hours 内只推一次；"
                   "文件缺失/损坏 ⇒ 当次允许推送并在文案标注（fail-closed，不静默吞）",
           "entries": dict(entries)}
    try:
        _dedup_path().parent.mkdir(parents=True, exist_ok=True)
        fd, tmpname = tempfile.mkstemp(prefix="alert_dedup-", suffix=".json", dir=str(_dedup_path().parent))
        os.close(fd)
        tmp = Path(tmpname)
        with tmp.open("w", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        tmp.replace(_dedup_path())
        return {"ok": True, "path": str(_dedup_path())}
    except OSError as exc:
        return {"ok": False, "path": str(_dedup_path()), "error": type(exc).__name__}


def check_and_record(*, checks_failed: Iterable[str] | None = None,
                     guards_failed: Iterable[str] | None = None,
                     severity: str | None = None,
                     error_kind: str | None = None,
                     is_emergency: bool = True,
                     now: dt.datetime | None = None) -> dict[str, Any]:
    """决定本轮是否允许推送，并（允许时）记录时间戳。

    返回：
      allowed            bool   True = 允许推送
      fingerprint        str    问题指纹（调用方可用于文案标注）
      reason             str    suppressed / first_seen / fingerprint_changed /
                              dedup_state_unavailable / not_emergency
      dedup_state        str    available / unavailable（含 reason）
      note               str    给用户看的一行说明（不可读时带原因）
      record_failed      bool   仅记录失败（不影响 allowed）
    """
    now = now or _now()
    fp = fingerprint_of(checks_failed=checks_failed, guards_failed=guards_failed,
                        severity=severity, error_kind=error_kind)

    result: dict[str, Any] = {"fingerprint": fp, "window_hours": WINDOW_H,
                              "dedup_state": "available", "record_failed": False}

    if not is_emergency:
        result.update({"allowed": False, "reason": "not_emergency",
                       "note": "非紧急：按仅紧急模式静默（与去重无关）"})
        return result

    state, status = _read_state()
    if not status.get("valid"):
        # ★ fail-closed 友好：不静默吞。允许推送 + 显式标注，让用户知道降滤器没生效。
        # ⚠️ 但**必须顺手把状态补起来**：否则文件永远缺失、每一轮都走这条分支，
        #    降频形同虚设（这正是"看着在守护其实没报"的镜像 bug）。
        #     补写失败也不影响本轮放行（只标注 record_failed）。
        result.update({
            "allowed": True,
            "reason": "dedup_state_unavailable",
            "dedup_state": "unavailable",
            "state_reason": status.get("reason"),
            "note": "告警降滤状态不可用（%s），本轮按未过滤处理" % status.get("reason"),
        })
        seeded = {
            fp: {
                "last_notified_at": _iso(now),
                "first_seen_at": _iso(now),
                "last_seen_at": _iso(now),
                "checks_failed": sorted({str(x) for x in (checks_failed or [])}),
                "guards_failed": sorted({str(x) for x in (guards_failed or [])}),
                "severity": str(severity or "").strip().lower(),
                "error_kind": str(error_kind or "").strip().lower()[:80],
                "notify_count": 1,
                "suppressed_count": 0,
                "seeded_after_state_loss": True,
            }
        }
        w = _write_state(seeded, now)
        result["record_failed"] = not w.get("ok", False)
        if result["record_failed"]:
            result["note"] += "（且状态补写失败：%s）" % w.get("error")
        else:
            result["note"] += "（已重建降滤状态，下一轮起生效）"
        return result

    # ⚠️ 不能先用 _prune 再取 prev：_prune 会**丢弃超窗条目**，而被丢弃的条目
    #    恰好是"超过 24h 应放行"的那一类 —— 先 prune 会让它们变成 first_seen，
    #    虽然结论（放行）一致，但 reason 会失真、审计上看不出"这是超窗放行"。
    #     正确顺序：先读原条目判定，再 prune 落盘。
    raw_entries = state.get("entries") or {}
    prev = raw_entries.get(fp) or {}
    prev_ts = _parse(prev.get("last_notified_at"))
    prev_guards = sorted(prev.get("guards_failed") or [])
    prev_checks = sorted(prev.get("checks_failed") or [])
    cur_guards = sorted({str(x) for x in (guards_failed or [])})
    cur_checks = sorted({str(x) for x in (checks_failed or [])})
    identity_changed = (prev_guards != cur_guards) or (prev_checks != cur_checks)
    entries = _prune(raw_entries, now)  # 仅用于落盘时的清理

    if prev_ts is None:
        result.update({"allowed": True, "reason": "first_seen",
                       "note": "首次出现该问题，放行"})
    elif identity_changed:
        result.update({"allowed": True, "reason": "fingerprint_changed",
                       "note": "问题构成变化（%s→%s / %s→%s），放行"
                               % (prev_checks, cur_checks, prev_guards, cur_guards)})
    elif (now - prev_ts).total_seconds() > WINDOW_H * 3600:
        result.update({"allowed": True, "reason": "window_elapsed",
                       "note": "距上次推送已超过 %gh，放行" % WINDOW_H,
                       "last_notified_at": _iso(prev_ts)})
    else:
        remain_h = max(0.0, WINDOW_H - (now - prev_ts).total_seconds() / 3600.0)
        result.update({"allowed": False, "reason": "suppressed",
                       "note": "同一问题 %gh 内已推送过（约 %.1fh 后可再报），本轮静默"
                               % (WINDOW_H, remain_h),
                       "last_notified_at": _iso(prev_ts),
                       "suppressed_count": int(prev.get("suppressed_count") or 0) + 1})
        # 被抑制也要记一次（让 suppressed_count 增长，便于审计"压了多少条")
        entries[fp] = dict(prev)
        entries[fp]["suppressed_count"] = result["suppressed_count"]
        entries[fp]["last_seen_at"] = _iso(now)
        w = _write_state(entries, now)
        result["record_failed"] = not w.get("ok", False)
        if result["record_failed"]:
            result["note"] += "（但状态写入失败：%s）" % w.get("error")
        return result

    # 放行 ⇒ 记录时间戳 + 累计推送次数
    entries[fp] = {
        "last_notified_at": _iso(now),
        "first_seen_at": prev.get("first_seen_at") or _iso(now),
        "last_seen_at": _iso(now),
        "checks_failed": cur_checks,
        "guards_failed": cur_guards,
        "severity": str(severity or "").strip().lower(),
        "error_kind": str(error_kind or "").strip().lower()[:80],
        "notify_count": int(prev.get("notify_count") or 0) + 1,
        "suppressed_count": int(prev.get("suppressed_count") or 0),
    }
    w = _write_state(entries, now)
    result["record_failed"] = not w.get("ok", False)
    if result["record_failed"]:
        result["note"] += "（状态写入失败：%s；不影响本轮推送）" % w.get("error")
    return result


def status_snapshot() -> dict[str, Any]:
    """只读快照（供值班手册 / 自检 / 审计）。"""
    state, st = _read_state()
    if not st.get("valid"):
        return {"state": "unavailable", "reason": st.get("reason"), "path": st.get("path"),
                "entries": 0}
    entries = state.get("entries") or {}
    return {"state": "available", "path": st.get("path"), "entries": len(entries),
            "window_hours": WINDOW_H, "updated_at": state.get("updated_at"),
            "fingerprints": sorted(entries.keys())}


__all__ = ["check_and_record", "fingerprint_of", "status_snapshot", "DEDUP_FILE", "WINDOW_H"]
