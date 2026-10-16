#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重置绑定端口的置信度基线并清除陈旧「送中」否决（防漂移收尾）。

背景：这些端口此前被自动换绑到 China 判定出口 → 引擎按洲际漂移打了 7 天 vetoUntil，
于是每 5 分钟被判定为「需自愈」，既持续漂移又在面板上显示为送中。
现在出口已回到美区，需把基线对齐到当前美区 IP/国别并清掉过期否决，
否则引擎会继续以旧基线判漂移 → 反复换绑。

只改 confidence_state.json（先备份），不碰 config.yaml / 账号绑定。
"""
from __future__ import annotations
import datetime as dt
import io
import json
import shutil
import sys
import time

sys.path.insert(0, r"D:\GitHub\AgentProxyHub")
from core.net_probe import probe_google_country_direct, probe_ip_direct  # noqa: E402

STATE = r"D:\Program Files\AgentProxyHub\data\confidence_state.json"
PORTS = [int(x) for x in sys.argv[1:]] or [21010, 21012, 21014, 21063, 21068, 21076, 22002]


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    live = {}
    for p in PORTS:
        st, ip, cc, ms = probe_ip_direct(p, 15)
        g = probe_google_country_direct(p, 15)
        live[p] = {"ip": ip, "cc": (cc or "").upper(), "google": g, "ms": ms}
        print(f"实测 {p}: google={g} phys={cc or '-'} ip={ip or '-'} {ms}ms")

    shutil.copyfile(STATE, f"{STATE}.bak-vetoclear-{time.strftime('%Y%m%d-%H%M%S')}")
    d = json.load(io.open(STATE, encoding="utf-8"))
    ports = d.setdefault("ports", {})
    for p in PORTS:
        m = live[p]
        if not m["ip"] or m["google"] != "United States":
            print(f"  跳过 {p}：当前未落在美区，保持原状")
            continue
        rec = ports.setdefault(str(p), {})
        before = (rec.get("vetoed"), rec.get("vetoUntil"), rec.get("baselineIp"),
                  rec.get("baselineCountry"), rec.get("driftPenalty"))
        rec["baselineIp"] = m["ip"]
        rec["baselineCountry"] = "UNITED STATES"
        rec["baselineGoogleCountry"] = "UNITED STATES"
        if m["cc"]:
            rec["baselinePhysicalCountry"] = m["cc"]
        rec["lastProbe"] = {"t": now, "ok": True, "ip": m["ip"], "country": m["cc"],
                            "googleCountry": "United States"}
        rec["vetoed"] = False
        rec["vetoReason"] = ""
        rec["vetoUntil"] = None
        rec["driftPenalty"] = 0
        rec["lastDriftUnknown"] = False
        rec["consecutiveFailures"] = 0
        rec["offline"] = False
        rec.setdefault("stableSince", now)
        rec["updatedAt"] = now
        print(f"  {p}: {before} -> vetoed=False vetoUntil=None baseline={m['ip']}/UNITED STATES")
    d["updatedAt"] = now
    with io.open(STATE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print("已写入", STATE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
