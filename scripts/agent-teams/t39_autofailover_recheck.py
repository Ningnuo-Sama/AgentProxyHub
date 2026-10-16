#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t39 F25-1 复核：连续采样确认 AT `proxy.proxy_pool.auto_failover` 恒为 False（api + 文件）。

纯 loopback；只打印该布尔键与时间戳，不打印任何凭据/URL。
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8045"
GUI_CONFIG = Path(r"C:\Users\1\.antigravity_tools\gui_config.json")
DSH_CREDS = Path(r"C:\Users\1\.dsh-beta\.credentials.yaml")
OUT = Path(r"D:\Program Files\AgentProxyHub\scratch\agent-teams\_t39_postrollback_recheck.json")


def _token() -> str:
    import yaml
    data = yaml.safe_load(DSH_CREDS.read_text(encoding="utf-8")) or {}
    return str((data.get("refs") or {}).get("FD_API_KEY") or "")


def api_value(auth: str):
    req = urllib.request.Request(BASE + "/api/config", method="GET")
    req.add_header("Authorization", f"Bearer {auth}")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return f"<http:{exc.code}>"
    except Exception as exc:  # noqa: BLE001
        return f"<{type(exc).__name__}>"
    node = payload.get("config") if isinstance(payload, dict) and isinstance(payload.get("config"), dict) else payload
    if not isinstance(node, dict):
        return f"<unexpected:{type(node).__name__}>"
    pool = ((node.get("proxy") or {}).get("proxy_pool") or {})
    if not pool:
        return f"<shape:{sorted(node.keys())[:6]}>"
    return pool.get("auto_failover")


def file_value():
    try:
        cfg = json.loads(GUI_CONFIG.read_text(encoding="utf-8-sig"))
        return cfg["proxy"]["proxy_pool"]["auto_failover"]
    except Exception as exc:  # noqa: BLE001
        return f"<{type(exc).__name__}>"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=150.0)
    parser.add_argument("--interval", type=float, default=15.0)
    args = parser.parse_args()
    auth = _token()
    samples = []
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        samples.append({"t": time.strftime("%H:%M:%S"), "api_auto_failover": api_value(auth),
                        "file_auto_failover": file_value(),
                        "file_mtime": time.strftime("%H:%M:%S", time.localtime(GUI_CONFIG.stat().st_mtime))})
        time.sleep(max(3.0, args.interval))
    bad = [s for s in samples if s["api_auto_failover"] is not False or s["file_auto_failover"] is not False]
    result = {"window_s": args.seconds, "samples": samples, "all_false": not bad, "bad": bad,
              "api_errors": [s for s in samples if isinstance(s["api_auto_failover"], str)]}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"window_s": args.seconds, "sample_count": len(samples), "all_false": not bad,
                      "bad": bad, "first": samples[0] if samples else None,
                      "last": samples[-1] if samples else None}, ensure_ascii=False, indent=2))
    return 0 if not bad and samples else 1


if __name__ == "__main__":
    raise SystemExit(main())
