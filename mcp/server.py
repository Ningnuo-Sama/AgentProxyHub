#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentProxyHub - Model Context Protocol (MCP) Server
标准 JSON-RPC 2.0 stdio 服务端，供 Claude Desktop、Cursor、DSH 等 Agent 调度使用
"""

import sys
import os
import json
import re
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

# 跨进程账本锁：MCP 可能被多个 Agent 客户端各拉一个实例（人手一个），
# 加上 CloakMulti GUI 共写 bindings.json，读-改-写必须整段持锁防丢更新。
BINDINGS_LOCK = os.path.join(DATA_DIR, "bindings.lock")

# Antigravity Tools 的账号粘性锚定（只读）。注意与上面的环境锁定账本是两码事：
# bindings.json 记「指纹浏览器环境 → 端口」，这里记「Google 账号 → 出口」，
# 由 FengWoBridge 出口面板与 Antigravity Tools 自己维护，本服务只读不写。
AG_CONFIG = os.environ.get("APHUB_ANTIGRAVITY_CONFIG") or r"C:\Users\1\.antigravity_tools\gui_config.json"
AG_ACCOUNTS = os.environ.get("APHUB_ANTIGRAVITY_ACCOUNTS") or r"C:\Users\1\.antigravity_tools\accounts.json"

# 本地出口桥接监听的端口段（FengWoBridge：蜂窝 21001-21080 + 星辰 22001-22045）
EXIT_PORT_MIN, EXIT_PORT_MAX = 21001, 22045

import contextlib

@contextlib.contextmanager
def _bindings_lock():
    import msvcrt
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(BINDINGS_LOCK, "a+b") as lf:
        msvcrt.locking(lf.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            lf.seek(0)
            msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, 1)

def get_nodes_data() -> Dict[str, Any]:
    """读取测绘节点数据。

    data/nodes.json 是合并超集（蜂窝源 + 星辰池由 core/ingest_xingchen.py 刷新），
    存在即优先；缺失时回退蜂窝运行副本。
    """
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
    # 原子写：tmp + os.replace，读方即使不持锁也看不到半截 JSON
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = BINDINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, BINDINGS_FILE)


def get_snapshot_info(data: Dict[str, Any]) -> Dict[str, Any]:
    """测绘快照的时间信息。

    节点评分是"上次实测"的结果而不是当前状态，必须把快照年龄一并交代，
    否则调用方会把 15 小时前的 S 级当成现在可用。
    """
    stamp = data.get("generatedAt")
    age = None
    if stamp:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                age = round((time.time() - time.mktime(time.strptime(stamp, fmt))) / 3600.0, 1)
                break
            except ValueError:
                continue
    return {"generated_at": stamp, "age_hours": age}


def probe_local_ports(listen: str, ports: List[int], timeout: float = 0.8) -> Dict[int, bool]:
    """对即将返回给调用方的端口做一次真实 TCP 预检。

    只做 TCP 连通性、不发请求：本地内核可能已经挂了，不给运行态就会把一堆
    连不上的端口当成可用出口返回（本项目就出过内核静默死亡、全部出口拒绝连接
    而测绘文件仍显示 S 级的情况）。
    """
    out: Dict[int, bool] = {}
    for p in ports:
        try:
            with socket.create_connection((listen, int(p)), timeout=timeout):
                out[int(p)] = True
        except OSError:
            out[int(p)] = False
    return out


def get_antigravity_stickiness() -> List[Dict[str, Any]]:
    """只读解析 Antigravity Tools 的账号粘性锚定（Google 账号 → 出口端口）。

    与 bindings.json 的环境锁定账本相互独立；解析失败一律返回空列表，
    绝不因为出口面板配置缺失而影响 MCP 其它能力。
    """
    if not os.path.exists(AG_CONFIG):
        return []
    try:
        with open(AG_CONFIG, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        pool = (cfg.get("proxy") or {}).get("proxy_pool") or {}
        proxies = pool.get("proxies") or []
        bound = pool.get("account_bindings") or {}
    except Exception:
        return []

    id_to_port: Dict[str, int] = {}
    id_to_name: Dict[str, str] = {}
    for px in proxies:
        pid = px.get("id")
        if not pid:
            continue
        m = re.search(r":(\d+)\s*$", str(px.get("url") or ""))
        if m:
            id_to_port[pid] = int(m.group(1))
        id_to_name[pid] = px.get("name") or ""

    email_by_id: Dict[str, str] = {}
    if os.path.exists(AG_ACCOUNTS):
        try:
            with open(AG_ACCOUNTS, "r", encoding="utf-8-sig") as f:
                for a in (json.load(f).get("accounts") or []):
                    if a.get("id"):
                        email_by_id[a["id"]] = a.get("email") or ""
        except Exception:
            pass

    rows: List[Dict[str, Any]] = []
    for acc_id, px_id in bound.items():
        rows.append({
            "account_id": acc_id,
            "account": email_by_id.get(acc_id) or "(未登记账号)",
            "port": id_to_port.get(px_id),
            "node_name": id_to_name.get(px_id) or "",
            "proxy_id": px_id,
        })
    return rows

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
    top = matched[:limit]

    # 运行态预检：只测即将返回的这几条，避免 125 次全量连接
    open_map = probe_local_ports(listen_ip, [m["port"] for m in top])
    for m in top:
        m["port_open"] = open_map.get(int(m["port"]), False)

    stickiness = get_antigravity_stickiness()
    account_by_port = {s["port"]: s["account"] for s in stickiness if s.get("port")}
    for m in top:
        m["account_bound"] = account_by_port.get(int(m["port"]))

    snap = get_snapshot_info(data)
    ready = any(open_map.values())
    out: Dict[str, Any] = {
        "scene": scene,
        "total_matched": len(matched),
        "results": top,
        "snapshot": snap,
        "local_exit": {
            "listen": listen_ip,
            "probed": len(top),
            "open": sum(1 for v in open_map.values() if v),
            "ready": ready,
        },
        "antigravity_account_stickiness": stickiness,
    }
    if not ready:
        out["warning"] = (
            "本地出口内核未运行或端口未监听：以上端口现在全部连不上。"
            r"请先启动 FengWoBridge 桥接（D:\Program Files\FengWoBridge\启动桥接.bat）。"
            "节点评分来自测绘快照，不代表当前可用性。"
        )
    elif snap.get("age_hours") is not None and snap["age_hours"] >= 6:
        out["warning"] = (
            f"测绘快照已 {snap['age_hours']} 小时未刷新，评分可能过期；"
            "端口存活已实测，但地区/送中判定以快照为准。"
        )
    return out

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

    with _bindings_lock():
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
    """查看环境锁定账本 + Antigravity 账号粘性锚定（两套绑定互不相干）"""
    bindings = get_bindings_data()
    return {
        "total_locked": len(bindings),
        "bindings": bindings,
        "ledger": "环境锁定账本：指纹浏览器环境 → 出口端口，本 MCP 与 CloakMulti 共写",
        "antigravity_account_stickiness": get_antigravity_stickiness(),
        "note": (
            "两套绑定含义不同，不要混用：bindings 是「环境 → 端口」；"
            "antigravity_account_stickiness 是「Google 账号 → 出口」，"
            "由 FengWoBridge 出口面板维护，本服务只读。bindings 为空只说明"
            "还没有环境锁过端口，不代表账号粘性不存在。"
        ),
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

CONFIDENCE_STATE_FILE = os.path.join(DATA_DIR, "confidence_state.json")


def tool_audit_confidence(args: Dict[str, Any]) -> Any:
    """读取节点时序置信度快照（core/confidence_engine.py 产出）。

    只读审计：返回各端口加权置信分、观察钟、漂移史与一票否决原因。
    可选 refresh=true 时同步触发一轮轻量巡检（现役绑定 + S/A 级端口），
    绝不自动改绑端口——老号迁移必须走上层人工/Agent 决策。
    """
    refresh = bool(args.get("refresh"))
    if refresh:
        import subprocess as _sp
        try:
            _sp.run([sys.executable, os.path.join(ROOT_DIR, "core", "confidence_engine.py"),
                     "--scope", str(args.get("scope", "bound"))],
                    capture_output=True, creationflags=0x08000000, timeout=300)
        except Exception as e:
            return {"ok": False, "error": f"巡检触发失败: {e}"}

    if not os.path.exists(CONFIDENCE_STATE_FILE):
        return {"ok": False, "error": "尚无置信度快照，请先 refresh=true 触发首轮巡检",
                "hint": "python core/confidence_engine.py"}

    try:
        with open(CONFIDENCE_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        return {"ok": False, "error": f"快照读取失败: {e}"}

    ports = state.get("ports", {})
    min_score = args.get("min_score")
    only_vetoed = bool(args.get("only_vetoed"))

    items = []
    for port, r in ports.items():
        if only_vetoed and not r.get("vetoed"):
            continue
        if min_score is not None and r.get("score", 0) < float(min_score):
            continue
        items.append({
            "port": int(port),
            "tier": r.get("tier"),
            "score": r.get("score"),
            "observeHours": r.get("observeHours"),
            "baseline": {"ip": r.get("baselineIp"), "country": r.get("baselineCountry")},
            "lastProbe": r.get("lastProbe"),
            "vetoed": r.get("vetoed", False),
            "vetoReason": r.get("vetoReason") or None,
            "recentDrifts": (r.get("driftEvents") or [])[-3:],
        })
    items.sort(key=lambda x: -x.get("score", 0))

    return {
        "ok": True,
        "updatedAt": state.get("updatedAt"),
        "total": len(items),
        "scoring": "物理稳定性40% + 大区合规30% + 协议健康30%；送中/离线/洲际漂移7天内一票否决",
        "note": "高分节点仅作为备选推荐，禁止据此强切老号绑定",
        "ports": items[: int(args.get("limit", 20))],
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
        "description": "按场景需求智能筛选最优本地出口端口 (如为 Claude 寻找美区住宅高分节点)；返回附带端口真实存活、测绘快照年龄与账号粘性",
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
        "description": "读取环境锁定账本（环境→端口）与 Antigravity 账号粘性锚定（账号→出口）；两者含义不同",
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
    },
    {
        "name": "audit_confidence",
        "description": "审计节点时序置信度：加权评分（稳定性40%/合规30%/健康30%）、观察钟、漂移史、一票否决；可选 refresh 触发实时巡检。只读，不改绑端口",
        "inputSchema": {
            "type": "object",
            "properties": {
                "refresh": {"type": "boolean", "description": "触发一轮实时巡检后再返回（默认 false）"},
                "scope": {"type": "string", "description": "巡检范围: bound(现役+S/A级) 或 all", "default": "bound"},
                "min_score": {"type": "number", "description": "只返回不低于该分数的端口"},
                "only_vetoed": {"type": "boolean", "description": "只看被一票否决的端口（风控高危清单）"},
                "limit": {"type": "integer", "description": "返回数量上限", "default": 20}
            }
        },
        "handler": tool_audit_confidence
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
