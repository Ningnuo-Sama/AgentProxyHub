#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentProxyHub - Model Context Protocol (MCP) Server
标准 JSON-RPC 2.0 stdio 服务端，供 Claude Desktop、Cursor、DSH 等 Agent 调度使用
"""

import sys
import os
import json
import time
import socket
from typing import Dict, Any, List, Optional

# 根目录定位
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
CONFIG_DIR = os.path.join(ROOT_DIR, "config")

NODES_FILE = os.path.join(DATA_DIR, "nodes.json")
SCENES_FILE = os.path.join(CONFIG_DIR, "scenes.json")
BINDINGS_FILE = os.path.join(DATA_DIR, "bindings.json")

# 兼容回退读取本地生产数据
FALLBACK_NODES = "D:\\Program Files\\FengWoBridge\\nodes.json"

def get_nodes_data() -> Dict[str, Any]:
    """读取测绘节点数据"""
    path = NODES_FILE if os.path.exists(NODES_FILE) else FALLBACK_NODES
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total": 0, "nodes": []}

def get_scenes_data() -> List[Dict[str, Any]]:
    """读取场景规则"""
    if os.path.exists(SCENES_FILE):
        try:
            with open(SCENES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def get_bindings_data() -> Dict[str, Any]:
    """读取环境与端口绑定记录"""
    if os.path.exists(BINDINGS_FILE):
        try:
            with open(BINDINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_bindings_data(data: Dict[str, Any]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(BINDINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ==============================================================================
# 工具实现函数
# ==============================================================================

def tool_list_scenes(args: Dict[str, Any]) -> Any:
    """列出系统支持的所有场景靶场及规则"""
    scenes = get_scenes_data()
    return {
        "count": len(scenes),
        "scenes": [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "desc": s.get("desc"),
                "chip": s.get("chip")
            } for s in scenes
        ]
    }

def tool_list_matched_proxies(args: Dict[str, Any]) -> Any:
    """按场景、国家、最低评分搜索并返回可用的本地端口"""
    scene = args.get("scene", "claude").lower()
    country = (args.get("country") or "").upper()
    min_rating = (args.get("min_rating") or "B").upper()
    limit = args.get("limit", 10)

    data = get_nodes_data()
    nodes = data.get("nodes", [])
    bindings = get_bindings_data()
    listen_ip = data.get("listen", "127.0.0.1")

    # 评分权重
    tier_weight = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0, "F": -1}
    min_w = tier_weight.get(min_rating, 2)

    matched = []
    for n in nodes:
        port = n.get("port")
        if not port:
            continue  # 无端口的测绘记录不可用，跳过而不是在后面崩掉

        # 1. 评分过滤
        rating = (n.get("healthRating") or "F").upper()
        if tier_weight.get(rating, -1) < min_w:
            continue

        # 2. 国家过滤
        c_code = (n.get("countryCode") or "").upper()
        c_name = (n.get("country") or "").upper()
        if country and country not in [c_code, c_name]:
            continue

        # 3. 场景判定
        is_ok = False
        scenes_dict = n.get("scenes") or {}
        if scene in scenes_dict:
            is_ok = bool(scenes_dict[scene])
        else:
            match_key = f"{scene}Supported"
            if match_key in n:
                is_ok = bool(n[match_key])
            elif scene == "claude":
                # 兼容未跑 Claude 专项探针时的智能规则兜底
                g_country = n.get("googleCountry") or ""
                is_sent = bool(n.get("isSentToChina", False))
                is_ok = (not is_sent and g_country in ["United States", "Japan", "United Kingdom", "Canada", "Germany", "Singapore", "Taiwan"])
            elif scene == "openai":
                g_country = n.get("googleCountry") or ""
                is_sent = bool(n.get("isSentToChina", False))
                is_ok = (not is_sent and g_country not in ["China", "Hong Kong", "Russia", "FAIL", "Unknown", ""])
            elif scene == "facebook":
                is_ok = (n.get("kind") in ["住宅/家宽", "移动网络"] and not bool(n.get("isDuplicateIp", False)))
            elif scene == "general":
                is_ok = (n.get("ip") is not None)

        if not is_ok:
            continue

        http_port = n.get("httpPort") or (port + 10000)
        bound = bindings.get(str(port))

        matched.append({
            "port": port,
            "http_port": http_port,
            "socks5_url": f"socks5://{listen_ip}:{port}",
            "http_url": f"http://{listen_ip}:{http_port}",
            "node_name": n.get("orig") or n.get("name"),
            "country": n.get("country"),
            "city": n.get("city"),
            "kind": n.get("kind"),
            "health_rating": rating,
            "health_score": n.get("healthScore"),
            "is_locked": bound is not None,
            "bound_profile": bound.get("profile") if bound else None
        })

    # 排序：未锁定的在前，按健康分降序；healthScore 缺失按 0 处理，避免 None 比较崩溃
    matched.sort(key=lambda x: (not x["is_locked"], x["health_score"] or 0), reverse=True)
    return {
        "scene": scene,
        "total_matched": len(matched),
        "results": matched[:limit]
    }

def tool_get_proxy_command(args: Dict[str, Any]) -> Any:
    """生成指定端口在终端、PowerShell 或 Chrome 上的挂载启动命令"""
    port = args.get("port", 21001)
    http_port = args.get("http_port") or (port + 10000)
    listen = "127.0.0.1"

    return {
        "port": port,
        "http_port": http_port,
        "powershell_env": f'$env:HTTP_PROXY="http://{listen}:{http_port}"; $env:HTTPS_PROXY="http://{listen}:{http_port}"; $env:ALL_PROXY="socks5://{listen}:{port}"',
        "bash_env": f'export HTTP_PROXY="http://{listen}:{http_port}" && export HTTPS_PROXY="http://{listen}:{http_port}" && export ALL_PROXY="socks5://{listen}:{port}"',
        "chrome_cli": f'--proxy-server="socks5://{listen}:{port}"',
        "claude_code_ready": f'$env:HTTP_PROXY="http://{listen}:{http_port}"; $env:HTTPS_PROXY="http://{listen}:{http_port}"; claude'
    }

def tool_bind_profile_proxy(args: Dict[str, Any]) -> Any:
    """将环境/Profile 与指定端口绑定，锁定 IP 粘性。端口已属于其他环境时拒绝，不静默抢占。"""
    profile = args.get("profile")
    port = args.get("port")
    note = args.get("note", "")

    if not profile or not port:
        return {"success": False, "error": "必须提供 profile 和 port 参数"}

    bindings = get_bindings_data()
    old = bindings.get(str(port))
    if old and old.get("profile") != profile:
        return {
            "success": False,
            "error": f"端口 {port} 已绑定给环境 [{old.get('profile')}]（{old.get('bound_at', '')}）；如需改绑请先解除原绑定"
        }

    bindings[str(port)] = {
        "profile": profile,
        "bound_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": note
    }
    save_bindings_data(bindings)

    return {
        "success": True,
        "bound_port": port,
        "profile": profile,
        "socks5_url": f"socks5://127.0.0.1:{port}",
        "message": f"成功锁定环境 [{profile}] 对应出口端口 {port}，维持 IP 粘性。"
    }

def tool_get_profile_bindings(args: Dict[str, Any]) -> Any:
    """查看当前所有环境的绑定锁定账本"""
    bindings = get_bindings_data()
    return {
        "total_locked": len(bindings),
        "bindings": bindings
    }

def _socks5_connect(listen: str, port: int, host: str, tport: int, timeout: float = 6.0) -> None:
    """极简 SOCKS5 客户端：无鉴权握手 + 域名 CONNECT，链路真实打通才返回。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((listen, int(port)))
        s.sendall(b"\x05\x01\x00")  # 问候：无鉴权
        resp = s.recv(2)
        if len(resp) < 2 or resp[0] != 5:
            raise OSError(f"非 SOCKS5 应答: {resp!r}")
        if resp[1] != 0:
            raise OSError(f"出口要求鉴权（method=0x{resp[1]:02x}），本地池应为免鉴权端口")
        addr = host.encode("idna") if all(ord(c) < 128 for c in host) else host.encode("utf-8")
        req = b"\x05\x01\x00\x03" + bytes([len(addr)]) + addr + int(tport).to_bytes(2, "big")
        s.sendall(req)
        rep = s.recv(10)
        if len(rep) < 2 or rep[0] != 5:
            raise OSError(f"CONNECT 应答异常: {rep!r}")
        if rep[1] != 0:
            reasons = {1: "一般性失败", 2: "规则不允许", 3: "网络不可达", 4: "主机不可达", 5: "连接被拒", 6: "TTL 过期", 7: "不支持的目标地址"}
            raise OSError(f"出口连接目标失败(rep={rep[1]}): {reasons.get(rep[1], '未知')}")
    finally:
        s.close()


def tool_test_proxy_target(args: Dict[str, Any]) -> Any:
    """真实穿 SOCKS5 链路测试端口对目标的连通性（不再只测本地 TCP 存活）。"""
    from urllib.parse import urlparse

    port = int(args.get("port", 21001))
    target = args.get("target", "https://api.anthropic.com")

    t0 = time.time()
    u = urlparse(target if "//" in target else f"https://{target}")
    thost = u.hostname or "api.anthropic.com"
    tport = u.port or (443 if u.scheme == "https" else 80)

    try:
        # 先确认本地端口在监听
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(4.0)
        s.connect(("127.0.0.1", port))
        s.close()
    except Exception as e:
        return {"port": port, "target": target, "alive": False, "error": f"本地端口不通: {e}"}

    try:
        _socks5_connect("127.0.0.1", port, thost, tport)
        return {
            "port": port,
            "target": target,
            "alive": True,
            "verified": True,
            "latency_ms": int((time.time() - t0) * 1000),
            "status": f"SOCKS5 链路已真实打通 {thost}:{tport}"
        }
    except Exception as e:
        return {
            "port": port,
            "target": target,
            "alive": False,
            "verified": False,
            "latency_ms": int((time.time() - t0) * 1000),
            "error": str(e)[:200]
        }

# ==============================================================================
# MCP 协议工具定义
# ==============================================================================

TOOLS = [
    {
        "name": "list_scenes",
        "description": "列出 AgentProxyHub 当前已配置的所有场景靶场 (如 反重力/Gemini, Claude专属, ChatGPT/OpenAI, Facebook社媒 等)",
        "inputSchema": {
            "type": "object",
            "properties": {}
        },
        "handler": tool_list_scenes
    },
    {
        "name": "list_matched_proxies",
        "description": "按场景需求智能筛选最优本地出口端口 (如为 Claude 寻找美区住宅高分节点)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene": {"type": "string", "description": "场景ID: claude, openai, antigravity, facebook, general", "default": "claude"},
                "country": {"type": "string", "description": "目标国家代码 (如 US, JP, SG, TW)"},
                "min_rating": {"type": "string", "description": "最低健康评级: S, A, B, C", "default": "B"},
                "limit": {"type": "integer", "description": "返回数量上限", "default": 5}
            }
        },
        "handler": tool_list_matched_proxies
    },
    {
        "name": "get_proxy_command",
        "description": "获取指定端口在 PowerShell、Bash、Chrome 或 Claude Code 命令行的一键挂载命令",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "SOCKS5 端口号 (如 21008)"},
                "http_port": {"type": "integer", "description": "可选对应 HTTP 端口号"}
            },
            "required": ["port"]
        },
        "handler": tool_get_proxy_command
    },
    {
        "name": "bind_profile_proxy",
        "description": "为指纹浏览器环境或自动化 Profile 锁定分配专属端口，维持长期 IP 粘性防风控封号",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile": {"type": "string", "description": "环境或账号唯一标识 (如 p1_twitter_01)"},
                "port": {"type": "integer", "description": "锁定的端口号 (如 21008)"},
                "note": {"type": "string", "description": "备注说明"}
            },
            "required": ["profile", "port"]
        },
        "handler": tool_bind_profile_proxy
    },
    {
        "name": "get_profile_bindings",
        "description": "读取当前所有环境与端口的绑定账本记录",
        "inputSchema": {
            "type": "object",
            "properties": {}
        },
        "handler": tool_get_profile_bindings
    },
    {
        "name": "test_proxy_target",
        "description": "现场测试指定本地端口的存活与网络延迟",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "端口号"},
                "target": {"type": "string", "description": "测试目标 URL"}
            },
            "required": ["port"]
        },
        "handler": tool_test_proxy_target
    }
]

# ==============================================================================
# JSON-RPC 2.0 stdio 循环分发器
# ==============================================================================

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        # notification（无 id）按协议不得回复，回了一条带 null id 的 result 会让部分客户端报错
        if req_id is None:
            continue

        if method == "initialize":
            res = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "AgentProxyHub",
                        "version": "1.0.0"
                    },
                    "capabilities": {
                        "tools": {}
                    }
                }
            }
        elif method == "tools/list":
            tools_spec = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": t["inputSchema"]
                } for t in TOOLS
            ]
            res = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": tools_spec}
            }
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments") or {}
            target_tool = next((t for t in TOOLS if t["name"] == tool_name), None)
            if target_tool:
                try:
                    call_result = target_tool["handler"](tool_args)
                    res = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(call_result, ensure_ascii=False, indent=2)
                                }
                            ]
                        }
                    }
                except Exception as e:
                    res = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32603, "message": str(e)}
                    }
            else:
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"}
                }
        else:
            res = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {}
            }

        sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
