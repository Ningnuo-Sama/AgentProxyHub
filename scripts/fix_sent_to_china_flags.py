#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速修复「送中」标记错位（stale isSentToChina / aiStatus）。

背景：Antigravity / Flow 绑定的端口在多个 nodes.json 快照里被长期标记为
「Google 已送中」，但实测早已不是中国判定（属于陈旧假判，2026-10-04 修过一次，
仓库与 FengWoBridge 的快照又退回了旧数据）。本脚本：

1. 扫描所有 nodes.json 快照，收集当前被标记送中（isSentToChina 或 googleCountry=China/HK/MO）
   的端口集合；
2. 用 core.net_probe 现场实测这些端口的 Google 自判国家与物理出口（纯 Python，零子进程、零黑窗）；
3. 按 gen-report.ps1 的同一判定规则回写：googleCountry / isSentToChina / aiStatus /
   antigravitySupported / healthScore / healthRating；
4. 写回前逐个备份（*.bak-sentfix-<时间戳>）。

只改 nodes.json 测绘快照，不改账号绑定、不改 config.yaml、不重启任何服务。
"""
from __future__ import annotations

import concurrent.futures
import glob
import json
import os
import shutil
import sys
import time

ROOT = r"D:\GitHub\AgentProxyHub"
sys.path.insert(0, ROOT)
from core.net_probe import probe_google_country_direct, probe_ip_direct  # noqa: E402

BLOCKED = {"China", "Hong Kong", "Macao", "Macau"}
AI_SUPPORTED = {
    "United States", "Canada", "United Kingdom", "Germany", "France", "Japan", "South Korea",
    "Taiwan", "Singapore", "Australia", "Spain", "Mexico", "Italy", "Switzerland",
    "Netherlands", "Sweden", "Poland",
}
SNAPSHOTS = [
    r"D:\GitHub\AgentProxyHub\data\nodes.json",
    r"D:\Program Files\AgentProxyHub\data\nodes.json",
    r"D:\Program Files\FengWoBridge\nodes.json",
]
STAMP = time.strftime("%Y%m%d-%H%M%S")


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


SCAN_JSON = os.path.join(ROOT, "scratch", "google_country_scan_20261014.json")


def flagged_ports():
    """快照里被标记送中的端口 + 最近一次全量实测中确凿送中的端口。"""
    ports = set()
    # 全量实测结果（若有）：把现场确凿送中/锁区的端口一并纳入复核
    if os.path.exists(SCAN_JSON):
        try:
            for r in load(SCAN_JSON):
                if r.get("google") in BLOCKED:
                    ports.add(int(r["port"]))
        except Exception as e:
            print(f"[提示] 读取全量实测快照失败: {e}")
    for p in SNAPSHOTS:
        if not os.path.exists(p):
            continue
        try:
            j = load(p)
        except Exception as e:
            print(f"[跳过] {p}: {e}")
            continue
        for n in j.get("nodes") or []:
            gc = n.get("googleCountry") or ""
            if n.get("isSentToChina") or gc in BLOCKED or (n.get("aiStatus") == "已送中"):
                ports.add(int(n["port"]))
    return sorted(ports)


def measure(port: int):
    g = probe_google_country_direct(port, 8)
    st, ip, cc, ms = probe_ip_direct(port, 10)
    return port, g, (cc or ""), (ip or "")


def decide(n, live):
    """按 gen-report.ps1 规则重算送中相关字段（物理国家优先取现场实测国码）。"""
    port, g, phys_cc, ip = live
    dead = (not ip)
    live_cc = (phys_cc or "").upper()
    stored = n.get("country") or ""
    # 物理出口是否本身就是锁区（中国大陆/香港/澳门）；实测国码优先，无实测时退回快照
    phys_blocked = live_cc in ("CN", "HK", "MO") or (not live_cc and stored in ("China", "Hong Kong"))
    sent = (g == "China") and (not phys_blocked)
    hk_or_cn = (g in ("China", "Hong Kong")) or phys_blocked
    ag_ok = (not dead) and (not hk_or_cn) and (not sent) and (g in AI_SUPPORTED)

    if dead:
        score, rating = 0, "F"
    elif hk_or_cn:
        score, rating = 0, "F"
    else:
        score = 75
        if ag_ok:
            score += 10
        if (n.get("orig") or "") and any(k in str(n.get("orig")) for k in ("专线", "原生")):
            score += 5
        score = max(0, min(100, score))
        rating = "S" if score >= 90 else "A" if score >= 80 else "B" if score >= 70 else "C"

    ai = "已送中" if sent else ("原生支持" if ag_ok else ("离线" if dead else "地区不支持"))
    return {
        "googleCountry": g,
        "isSentToChina": bool(sent),
        "antigravitySupported": bool(ag_ok),
        "healthScore": score,
        "healthRating": rating,
        "aiStatus": ai,
        "_live_phys": phys_cc,
        "_live_ip": ip,
    }


def main() -> int:
    ports = flagged_ports()
    print(f"[1/3] 快照中被标记送中的端口 {len(ports)} 个: {ports}")

    print("[2/3] 现场实测（纯 Python SOCKS5+TLS，零子进程）...")
    live = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        for port, g, cc, ip in ex.map(measure, ports):
            live[port] = (port, g, cc, ip)
            print(f"   {port}\tgoogle={g}\tphys={cc or '-'}\tip={ip or '-'}")

    print("[3/3] 回写快照...")
    for path in SNAPSHOTS:
        if not os.path.exists(path):
            print(f"   [缺失] {path}")
            continue
        j = load(path)
        changed = []
        for n in j.get("nodes") or []:
            p = int(n.get("port") or 0)
            if p not in live:
                continue
            before = (n.get("googleCountry"), bool(n.get("isSentToChina")), n.get("aiStatus"),
                      bool(n.get("antigravitySupported")), n.get("healthRating"))
            new = decide(n, live[p])
            for k in ("googleCountry", "isSentToChina", "antigravitySupported",
                      "healthScore", "healthRating", "aiStatus"):
                n[k] = new[k]
            after = (new["googleCountry"], new["isSentToChina"], new["aiStatus"],
                     new["antigravitySupported"], new["healthRating"])
            if before != after:
                changed.append((p, before, after))
        if changed:
            shutil.copyfile(path, f"{path}.bak-sentfix-{STAMP}")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(j, f, ensure_ascii=False, indent=1)
            print(f"   {path}  -> 修正 {len(changed)} 条（已备份 .bak-sentfix-{STAMP}）")
            for p, b, a in changed:
                print(f"      {p}: {b} -> {a}")
        else:
            print(f"   {path}  -> 无需修正")

    print("\n== 修复完成（仅数据快照，未动账号绑定/配置/服务）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
