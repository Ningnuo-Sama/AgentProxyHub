#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把蜂窝桥（FengWoBridge）的最新测绘同步进 AgentProxyHub data/nodes.json。

蜂窝的 gen-config.ps1 / 巡检已聚合双机场（蜂窝 21001+ / 星辰 22001+）并完成探测评级，
AgentProxyHub 不重复建设端口池——本脚本只做「同步 + 双源标注」，供面板 / MCP /
CloakMulti 三个消费方使用。每次蜂窝巡检后跑一遍即可刷新（幂等，原子写）。

用法：python core/sync_nodes.py
"""
import json
import os
import sys
import time

# WindowsApps 的 python 垫片跑脚本时不定义 __file__，用 sys.argv[0] 兜底
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.path.dirname(os.path.abspath(sys.argv[0] or os.getcwd()))
ROOT = os.path.dirname(_HERE)
NODES_OUT = os.path.join(ROOT, "data", "nodes.json")
FENGWO_NODES = r"D:\Program Files\FengWoBridge\nodes.json"


# 端口段 → 上游名（蜂窝桥的双机场聚合约定，见其 config.yaml 头部注释）
def port_source(port: int) -> str:
    if 21001 <= port < 22000:
        return "蜂窝(FengWo)"
    if 22001 <= port < 23000:
        return "星辰(Xingchen)"
    return "其他"


def main() -> int:
    if not os.path.exists(FENGWO_NODES):
        print(f"[失败] 蜂窝测绘数据不存在: {FENGWO_NODES}")
        return 1
    try:
        fw = json.load(open(FENGWO_NODES, encoding="utf-8"))
    except ValueError as exc:
        print(f"[失败] 蜂窝 nodes.json 不是合法 JSON: {exc}")
        return 1

    nodes = fw.get("nodes", [])
    sources: dict = {}
    for n in nodes:
        src = port_source(n.get("port") or 0)
        n["upstream"] = n.get("upstream") or src
        sources[src] = sources.get(src, 0) + 1

    out = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "listen": fw.get("listen", "127.0.0.1"),
        "total": len(nodes),
        "alive": sum(1 for n in nodes if (n.get("healthRating") or "F") != "F"),
        "sources": sources,
        "nodes": nodes,
    }
    os.makedirs(os.path.dirname(NODES_OUT), exist_ok=True)
    tmp = NODES_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, NODES_OUT)
    print(f"[完成] 同步 {len(nodes)} 个出口 -> data/nodes.json（{sources}，存活 {out['alive']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
