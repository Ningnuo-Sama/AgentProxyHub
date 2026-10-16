#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t24 流量实测：**2 s × 60 s 分桶采样**（t3 `traffic-plan.md` §1.5 口径）。

为什么不能用单次 `/connections` 差值：t3 实测 130 s 窗口 = 0 B、330 s 窗口 = 1.3 MB，
单点采样会骗人。本脚本每 2 s 采一次，按 `metadata.inboundPort` 分桶，
对每条连接取「本窗口内观测到的最大 upload/download」累加——短连接也能被采到。

纯粹 loopback（127.0.0.1:21909），不产生 WAN 字节。
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

CONFIG = Path(r"D:\Program Files\AgentProxyHub\config\config.yaml")
API = "http://127.0.0.1:21909"


def _secret() -> str:
    try:
        import yaml
        return str((yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}).get("secret") or "")
    except Exception:  # noqa: BLE001
        return ""


def _connections(secret: str) -> dict:
    req = urllib.request.Request(API + "/connections", method="GET")
    if secret:
        req.add_header("Authorization", f"Bearer {secret}")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (OSError, urllib.error.URLError, ValueError, TimeoutError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="2s x 60s 分桶流量采样（loopback，0 WAN）")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--label", default="window")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    secret = _secret()
    first = _connections(secret)
    total0 = (first.get("downloadTotal") or 0) + (first.get("uploadTotal") or 0)
    per_conn: dict[str, dict[str, float]] = {}
    per_port: dict[str, dict[str, float]] = {}
    samples = 0
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        snap = _connections(secret)
        samples += 1
        for row in snap.get("connections") or []:
            cid = str(row.get("id") or "")
            down = float(row.get("download") or 0)
            up = float(row.get("upload") or 0)
            prev = per_conn.get(cid)
            if prev is None or (down + up) > (prev["download"] + prev["upload"]):
                per_conn[cid] = {"download": down, "upload": up}
                port = str((row.get("metadata") or {}).get("inboundPort") or "unknown")
                bucket = per_port.setdefault(port, {"download": 0.0, "upload": 0.0, "connections": 0})
                bucket["download"] = max(bucket["download"], down)
                bucket["upload"] = max(bucket["upload"], up)
        time.sleep(max(0.2, args.interval))

    last = _connections(secret)
    total1 = (last.get("downloadTotal") or 0) + (last.get("uploadTotal") or 0)
    window_bytes = sum(b["download"] + b["upload"] for b in per_port.values())
    report = {
        "label": args.label,
        "sampling": {"interval_s": args.interval, "samples": samples, "window_s": args.seconds},
        "global_counter_delta": {"downloadTotal_delta": (last.get("downloadTotal") or 0) - (first.get("downloadTotal") or 0),
                                 "uploadTotal_delta": (last.get("uploadTotal") or 0) - (first.get("uploadTotal") or 0),
                                 "total_delta": total1 - total0,
                                 "note": "全局计数器含全部经本内核的业务流量，不能用于给巡检归因"},
        "bucketed_window_bytes": int(window_bytes),
        "per_port": {k: {"download": int(v["download"]), "upload": int(v["upload"]),
                         "total": int(v["download"] + v["upload"])}
                     for k, v in sorted(per_port.items())},
        "observed_connections": len(per_conn),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
