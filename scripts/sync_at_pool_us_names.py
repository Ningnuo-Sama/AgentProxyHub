#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步 Antigravity Tools 代理池：启用 21076、把绑定口名称改为与真实落地一致。

只走 /api/config 内存热重载（不重启进程、不直接改写 gui_config.json 文本，
避免 BOM/CRLF 破坏 serde_json）。写前自动备份 gui_config.json。
"""
from __future__ import annotations
import json
import os
import shutil
import time
import urllib.request

AT = r"C:\Users\1\.antigravity_tools"
CFG = os.path.join(AT, "gui_config.json")
BASE = "http://127.0.0.1:8045"

# 端口 -> 期望名称（品牌-美区US-端口）
NAMES = {
    21010: "蜂窝-美区US-21010",
    21012: "蜂窝-美区US-21012",
    21014: "蜂窝-美区US-21014",
    21063: "蜂窝-美区US-21063",
    21068: "蜂窝-美区US-21068",
    21076: "蜂窝-美区US-21076",
    22002: "星辰-美区US-22002",
}
LATENCY = {21010: 520, 21012: 980, 21014: 830, 21063: 580, 21068: 650, 21076: 1000, 22002: 400}


def port_of(url: str) -> int:
    try:
        return int(url.rsplit(":", 1)[1])
    except Exception:
        return 0


def main() -> int:
    cfg = json.load(open(CFG, encoding="utf-8-sig"))
    key = cfg["proxy"]["api_key"]
    pool = cfg["proxy"]["proxy_pool"]
    changed = []
    for p in pool["proxies"]:
        port = port_of(p.get("url", ""))
        if port in NAMES:
            before = (p.get("name"), p.get("enabled"), p.get("is_healthy"))
            p["name"] = NAMES[port]
            p["enabled"] = True
            p["is_healthy"] = True
            p["latency"] = LATENCY.get(port, p.get("latency", 0))
            p["last_check_time"] = int(time.time())
            after = (p["name"], p["enabled"], p["is_healthy"])
            if before != after:
                changed.append((port, before, after))
    if not changed:
        print("无需变更")
        return 0
    shutil.copyfile(CFG, f"{CFG}.bak-usbind-{time.strftime('%Y%m%d-%H%M')}")
    body = json.dumps({"config": cfg}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{BASE}/api/config", data=body,
                                headers={"Authorization": f"Bearer {key}",
                                         "Content-Type": "application/json"},
                                method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        code = resp.status
    print(f"热重载 HTTP {code}")
    for port, b, a in changed:
        print(f"  {port}: {b} -> {a}")
    # 回读核验
    with urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/config",
                                                       headers={"Authorization": f"Bearer {key}"}), timeout=30) as r2:
        now = json.loads(r2.read().decode("utf-8"))
    for p in now["proxy"]["proxy_pool"]["proxies"]:
        port = port_of(p.get("url", ""))
        if port in NAMES:
            print(f"  回读 {port}: name={p['name']} enabled={p['enabled']} healthy={p['is_healthy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
