#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AgentProxyHub 核心端口池同步与节点测绘维护引擎。

从 AgentProxyHub 自有端口池（蜂窝 21001-21080 / 星辰 22001-22045）及探针输出同步最新测绘，
负责多上游聚合、数据标准化与原子写入 data/nodes.json，供面板、MCP Server 与 CloakMulti 消费。

用法：
    python core/sync_nodes.py            # 从本地端口池与测绘结果同步
    python core/sync_nodes.py --rebuild  # 触发 gen-config.ps1 重新建池后再同步
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.path.dirname(os.path.abspath(sys.argv[0] or os.getcwd()))
ROOT = os.path.dirname(_HERE)
DATA_DIR = os.path.join(ROOT, "data")
NODES_OUT = os.path.join(DATA_DIR, "nodes.json")
PORT_MAP_CSV = os.path.join(DATA_DIR, "port_map.csv")
ALT_PORT_MAP_CSV = os.path.join(ROOT, "端口对照.csv")
BRIDGE_JSON = os.path.join(ROOT, "config", "bridge.json")
GEN_CONFIG_SCRIPT = os.path.join(_HERE, "gen-config.ps1")
GEN_REPORT_SCRIPT = os.path.join(_HERE, "gen-report.ps1")

# 过渡兼容路径
LEGACY_FENGWO_NODES = r"D:\Program Files\FengWoBridge\nodes.json"


def port_source(port: int) -> str:
    """根据端口号划分上游机场来源。"""
    if 21001 <= port < 22000:
        return "蜂窝(FengWo)"
    if 22001 <= port < 23000:
        return "星辰(Xingchen)"
    return "通用代理"


def rebuild_port_pool() -> bool:
    """调用 core/gen-config.ps1 重新生成本地 mihomo 配置与端口池。"""
    if not os.path.exists(GEN_CONFIG_SCRIPT):
        print(f"[错误] 建池脚本不存在: {GEN_CONFIG_SCRIPT}")
        return False
    print("[建池] 正在执行 core/gen-config.ps1 重建端口池配置...")
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        GEN_CONFIG_SCRIPT,
        "-RootDir",
        ROOT,
    ]
    res = subprocess.run(cmd)
    return res.returncode == 0


def load_port_map() -> list:
    """读取本地端口池映射表。"""
    csv_file = PORT_MAP_CSV if os.path.exists(PORT_MAP_CSV) else ALT_PORT_MAP_CSV
    if not os.path.exists(csv_file):
        return []
    rows = []
    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                p = int(r.get("ListenPort") or r.get("port") or 0)
                if p > 0:
                    rows.append(
                        {
                            "port": p,
                            "httpPort": int(r.get("HttpPort") or (p + 10000)),
                            "name": r.get("ProxyName") or f"node-{p}",
                            "orig": r.get("OrigName") or "",
                            "airport": r.get("Airport") or port_source(p),
                            "type": r.get("Type") or "socks5",
                            "server": r.get("Server") or "",
                            "serverPort": int(r.get("ServerPort") or 0),
                        }
                    )
            except Exception:
                continue
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentProxyHub 节点同步与建池引擎")
    parser.add_argument("--rebuild", action="store_true", help="先执行 gen-config.ps1 重建端口池")
    args = parser.parse_args()

    if args.rebuild:
        if not rebuild_port_pool():
            print("[警告] 建池脚本执行未完成，继续尝试同步已有数据")

    # 1. 优先从本地 data/nodes.json 读取已有全量测绘
    existing_nodes_map = {}
    listen_addr = "127.0.0.1"
    if os.path.exists(NODES_OUT):
        try:
            with open(NODES_OUT, "r", encoding="utf-8") as f:
                cur = json.load(f)
                listen_addr = cur.get("listen", "127.0.0.1")
                for n in cur.get("nodes", []):
                    p = n.get("port")
                    if p:
                        existing_nodes_map[p] = n
        except Exception as e:
            print(f"[提示] 读取本地 nodes.json 异常: {e}")

    # 2. 如果本地无历史测绘，但过渡期旧桥有数据，继承其测绘评级
    if not existing_nodes_map and os.path.exists(LEGACY_FENGWO_NODES):
        try:
            with open(LEGACY_FENGWO_NODES, "r", encoding="utf-8") as f:
                leg = json.load(f)
                listen_addr = leg.get("listen", "127.0.0.1")
                for n in leg.get("nodes", []):
                    p = n.get("port")
                    if p:
                        existing_nodes_map[p] = n
            print(f"[迁移] 从旧桥平滑继承 {len(existing_nodes_map)} 个节点的测绘评级")
        except Exception as e:
            print(f"[提示] 读取旧桥节点数据失败: {e}")

    # 3. 读取本地端口映射表
    port_pool = load_port_map()
    merged_nodes = []
    sources = {}

    if port_pool:
        for item in port_pool:
            p = item["port"]
            src = port_source(p)
            sources[src] = sources.get(src, 0) + 1

            if p in existing_nodes_map:
                node = existing_nodes_map[p]
                # 更新基础元信息，保留测绘评级
                node["name"] = item["name"]
                node["orig"] = item["orig"] or node.get("orig", "")
                node["airport"] = item["airport"]
                node["upstream"] = f"{item['server']}:{item['serverPort']}" if item["server"] else node.get("upstream", "")
                node["source"] = src
            else:
                # 本地新发现的端口条目
                node = {
                    "port": p,
                    "httpPort": item["httpPort"],
                    "name": item["name"],
                    "orig": item["orig"],
                    "type": item["type"],
                    "upstream": f"{item['server']}:{item['serverPort']}" if item["server"] else "upstream",
                    "kind": "未知",
                    "airport": item["airport"],
                    "source": src,
                    "googleCountry": "FAIL",
                    "isSentToChina": False,
                    "isDuplicateIp": False,
                    "healthScore": 0,
                    "healthRating": "F",
                    "antigravitySupported": False,
                    "claudeSupported": False,
                    "openaiSupported": False,
                    "facebookSupported": False,
                    "generalSupported": False,
                    "scenes": {
                        "antigravity": False,
                        "claude": False,
                        "openai": False,
                        "facebook": False,
                        "general": False,
                    },
                    "boundProfile": None,
                }
            merged_nodes.append(node)
    else:
        # 如果没有 CSV，直接使用现有节点
        merged_nodes = list(existing_nodes_map.values())
        for n in merged_nodes:
            src = port_source(n.get("port") or 0)
            n["source"] = src
            sources[src] = sources.get(src, 0) + 1

    merged_nodes.sort(key=lambda x: x.get("port", 0))

    out = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "listen": listen_addr,
        "total": len(merged_nodes),
        "alive": sum(1 for n in merged_nodes if (n.get("healthRating") or "F") != "F"),
        "sources": sources,
        "claudeReady": sum(1 for n in merged_nodes if n.get("claudeSupported")),
        "openaiReady": sum(1 for n in merged_nodes if n.get("openaiSupported")),
        "fbReady": sum(1 for n in merged_nodes if n.get("facebookSupported")),
        "antigravityReady": sum(1 for n in merged_nodes if n.get("antigravitySupported")),
        "nodes": merged_nodes,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = NODES_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, NODES_OUT)

    print(f"[完成] AgentProxyHub 端口池维护成功：共 {len(merged_nodes)} 个出口（{sources}，存活 {out['alive']}） -> {NODES_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
