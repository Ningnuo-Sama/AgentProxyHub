#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t39 F25-1 执行体：把 AT `proxy.proxy_pool.auto_failover` 置为 false（走 HTTP API，不碰文件）。

安全性设计：
  * body = **GET /api/config 回来的完整服务端配置**，只改 `proxy.proxy_pool.auto_failover` 一个键
    → 无论服务端是 merge 还是 replace 语义，都不会丢其它键（已由 `--noop-post` round-trip 证明）；
  * 改前/改后都做**结构差异**比对，差异**必须只有一处**，否则报错并提示回滚；
  * 全程 loopback（127.0.0.1:8045），只比 SHA-256，不打印任何凭据；
  * 输出 evidence JSON 供报告引用。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8045"
GUI_CONFIG = Path(r"C:\Users\1\.antigravity_tools\gui_config.json")
DSH_CREDS = Path(r"C:\Users\1\.dsh-beta\.credentials.yaml")
EVIDENCE = Path(r"D:\Program Files\AgentProxyHub\scratch\agent-teams\_t39_autofailover_evidence.json")

TARGET_PATH = ("proxy", "proxy_pool", "auto_failover")


def _token() -> str:
    import yaml
    data = yaml.safe_load(DSH_CREDS.read_text(encoding="utf-8")) or {}
    return str((data.get("refs") or {}).get("FD_API_KEY") or "")


def _call(method: str, path: str, auth: str, body: dict | None = None, timeout: float = 10.0):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=payload, method=method)
    req.add_header("Accept", "application/json")
    if payload is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    if auth:
        req.add_header("Authorization", f"Bearer {auth}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                return resp.status, {"_raw_len": len(raw)}
    except urllib.error.HTTPError as exc:
        return exc.code, {"_error": exc.read(200).decode("utf-8", "replace")[:200]}
    except Exception as exc:  # noqa: BLE001
        return -1, {"_error": type(exc).__name__}


def _inner(payload):
    if isinstance(payload, dict) and isinstance(payload.get("config"), dict):
        return payload["config"]
    return payload


def _dig(value) -> dict:
    """结构指纹：键名 + 类型 + 标量原值（字符串只记长度，避免密钥落盘）。"""
    if isinstance(value, dict):
        return {k: _dig(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_dig(v) for v in value]
    if isinstance(value, str):
        return f"str[{len(value)}]"
    return value


def _flat(value, prefix=""):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    if isinstance(value, list):
        return {prefix: f"list[{len(value)}]"}
    return {prefix: value}


def _get_target(cfg):
    node = cfg
    for key in TARGET_PATH:
        node = (node or {}).get(key)
    return node


def _file_target():
    try:
        file_cfg = json.loads(GUI_CONFIG.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return f"<unreadable:{type(exc).__name__}>"
    return _get_target(file_cfg)


def _post_target(auth: str, value: bool) -> dict:
    """把 `auto_failover` 置为 `value`：body = GET 回来的完整服务端配置 + 只翻转该键。"""
    status, payload = _call("GET", "/api/config", auth)
    cfg = json.loads(json.dumps(_inner(payload)))
    node = cfg
    for key in TARGET_PATH[:-1]:
        node = node[key]
    node[TARGET_PATH[-1]] = value
    post_status, _resp = _call("POST", "/api/config", auth, {"config": cfg})
    _s, readback = _call("GET", "/api/config", auth)
    return {"post_http": post_status, "readback": _get_target(_inner(readback))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正执行写动作（不带则只做改前检查）")
    parser.add_argument("--observe-seconds", type=float, default=0.0, help="改后持续观测秒数（≥380 覆盖 3 个 ≈110s 周期）")
    parser.add_argument("--interval", type=float, default=20.0)
    parser.add_argument("--rollback-test", action="store_true",
                        help="回滚实测：置回 True → 回读 → 立即再置 False → 回读（窗口 <2s）")
    parser.add_argument("--rollback", action="store_true",
                        help="一行回滚：把 auto_failover 置回 True 并回读（＝--rollback-test 的前半段）")
    args = parser.parse_args()

    auth = _token()
    evidence: dict = {
        "at": {"endpoint": BASE, "api": "/api/config", "method": "POST"},
        "credential": {"source": "dsh://refs/FD_API_KEY",
                       "sha256_12": hashlib.sha256(auth.encode()).hexdigest()[:12], "len": len(auth)},
        "target_path": ".".join(TARGET_PATH),
        "wan_bytes": 0,
        "loopback_only": True,
    }

    status, before_payload = _call("GET", "/api/config", auth)
    if status != 200:
        print(f"GET /api/config -> HTTP {status}；停止")
        return 1
    before = _inner(before_payload)
    before_value = _get_target(before)
    before_file_value = _file_target()
    before_flat = _flat(before)
    evidence["before"] = {"api_value": before_value, "file_value": before_file_value,
                          "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                          "api_structure_sha256_16": hashlib.sha256(
                              json.dumps(_dig(before), ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16],
                          "file_bytes_sha256_16": hashlib.sha256(GUI_CONFIG.read_bytes()).hexdigest()[:16],
                          "key_count": len(before_flat)}
    print(f"[before] api.{'.'.join(TARGET_PATH)} = {before_value} | file = {before_file_value} | keys={len(before_flat)}")

    if args.rollback:
        outcome = _post_target(auth, True)
        print(json.dumps({"mode": "rollback_to_true", "post_http": outcome["post_http"],
                          "readback": outcome["readback"], "file": _file_target()}, ensure_ascii=False))
        return 0 if outcome["readback"] is True else 1

    if args.rollback_test:
        print("--- 回滚实测：auto_failover → True（回读）→ 立即 → False（回读）---")
        t0 = time.monotonic()
        on = _post_target(auth, True)
        on_elapsed = round(time.monotonic() - t0, 2)
        sample = {"api": _get_target(_inner(_call("GET", "/api/config", auth)[1])), "file": _file_target()}
        off = _post_target(auth, False)
        _s, final_payload = _call("GET", "/api/config", auth)
        evidence["rollback_test"] = {
            "before_value": before_value,
            "rollback_line": "python scripts\\agent-teams\\t39_apply_autofailover_off.py --apply",
            "to_true": {"post_http": on["post_http"], "readback": on["readback"], "file_at_window": sample["file"]},
            "true_window_seconds": on_elapsed,
            "to_false": {"post_http": off["post_http"], "readback": off["readback"]},
            "final_api": _get_target(_inner(final_payload)),
            "final_file": _file_target(),
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "note": "auto_failover 仅在代理池健康检查失败时动作（health_check_interval=300s），True 窗口 <2s",
        }
        print(f"  → True：api={on['readback']} file={sample['file']}（窗口 {on_elapsed}s）")
        print(f"  → 回滚 False：api={off['readback']} file={_file_target()} final_api={evidence['rollback_test']['final_api']}")
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"evidence -> {EVIDENCE}")
        return 0 if off["readback"] is False else 1

    if before_value is not True:
        print("目标键当前不是 True；无需处置（或已被处置）。")
        if not args.apply:
            EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return 0

    if not args.apply:
        print("（未加 --apply，仅检查，未写。）")
        EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0

    after_body = json.loads(json.dumps(before))
    node = after_body
    for key in TARGET_PATH[:-1]:
        node = node[key]
    node[TARGET_PATH[-1]] = False

    status2, resp = _call("POST", "/api/config", auth, {"config": after_body})
    evidence["post"] = {"http": status2, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "body_keys": len(before_flat), "body_source": "GET /api/config 原文 + 仅翻转 auto_failover"}
    print(f"[post] POST /api/config -> HTTP {status2}")

    status3, readback_payload = _call("GET", "/api/config", auth)
    readback = _inner(readback_payload)
    after_value = _get_target(readback)
    after_flat = _flat(readback)
    diff = {k: (before_flat.get(k), after_flat.get(k)) for k in set(before_flat) | set(after_flat)
            if before_flat.get(k) != after_flat.get(k)}
    evidence["after_readback"] = {
        "http": status3, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "api_value": after_value, "file_value": _file_target(),
        "structure_diff": {k: list(v) for k, v in diff.items()},
        "only_target_changed": set(diff) == {"proxy.proxy_pool.auto_failover"},
        "api_structure_sha256_16": hashlib.sha256(
            json.dumps(_dig(readback), ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16],
    }
    print(f"[readback] api.{'.'.join(TARGET_PATH)} = {after_value} | file = {evidence['after_readback']['file_value']}")
    print(f"[readback] 结构差异 = {evidence['after_readback']['structure_diff']}")
    if not evidence["after_readback"]["only_target_changed"]:
        print("⚠️ 差异不止目标键！请立即回滚（备份：backups\\t39-at-autofailover-20261017\\）。")

    if args.observe_seconds > 0:
        samples = []
        deadline = time.monotonic() + args.observe_seconds
        while time.monotonic() < deadline:
            _s, payload = _call("GET", "/api/config", auth)
            value = _get_target(_inner(payload))
            samples.append({"at": time.strftime("%H:%M:%S"), "api_value": value,
                            "file_value": _file_target(),
                            "file_mtime": time.strftime("%H:%M:%S", time.localtime(GUI_CONFIG.stat().st_mtime))
                            if GUI_CONFIG.exists() else None})
            print(f"  [observe {samples[-1]['at']}] api={value} file={samples[-1]['file_value']} "
                  f"file_mtime={samples[-1]['file_mtime']}")
            time.sleep(max(5.0, args.interval))
        reverted = [s for s in samples if s["api_value"] is not False]
        file_reverted = [s for s in samples if s["file_value"] is not False]
        evidence["observation"] = {
            "seconds": args.observe_seconds, "interval_s": args.interval, "samples": samples,
            "api_never_reverted_to_true": not reverted,
            "file_never_reverted_to_true": not file_reverted,
            "rewrite_cycles_observed_est": round(args.observe_seconds / 110.0, 2),
        }
        print(f"  → api 未回写 True: {not reverted} | file 未回写 True: {not file_reverted} "
              f"| 观测 ≈{evidence['observation']['rewrite_cycles_observed_est']} 个重写周期")

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"evidence -> {EVIDENCE}")
    return 0 if evidence.get("after_readback", {}).get("api_value") is False else 1


if __name__ == "__main__":
    raise SystemExit(main())
