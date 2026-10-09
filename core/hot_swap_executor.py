#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AgentProxyHub 底层节点热替换与自愈执行器 (Hot Swap Executor).

核心契约（铁律）：
1. 粘性端口神圣不可侵犯：业务层（Antigravity、Flow-Tools、指纹浏览器）绑定的本地端口永远不变。
2. 只换节点，不换端口：当端口底层物理节点失效、离线或“送中”（GoogleCountry 判为 China）时，
   只在 AgentProxyHub 底座热替换该端口映射的上游 Proxy 节点。
3. 大区一致性与防漂移：同国优先，其次同大区（美区->美区，东亚->东亚），严禁跨洲/跨大区盲目切换。
4. 无感热重载与快速回滚：修改配置后通过 Mihomo Controller API (21909) 热重载；若新出口仍异常立即回滚。
5. 审计留痕与本地通知：每次热替换落盘 repair_events.jsonl，并向鲸管家发送气泡提醒。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APHUB_DATA_DIR") or ROOT_DIR / "data")
PROD_DIR = Path(r"D:\Program Files\AgentProxyHub")
CONFIG_PATH = PROD_DIR / "config" / "config.yaml" if (PROD_DIR / "config" / "config.yaml").exists() else ROOT_DIR / "config" / "config.yaml"
BACKUP_DIR = PROD_DIR / "backups" if PROD_DIR.exists() else ROOT_DIR / "backups"
OPERATIONS_DIR = Path(r"D:\ProgramData\AgentProxyHub\operations")
REPAIR_EVENTS_FILE = OPERATIONS_DIR / "repair_events.jsonl"
CONFIDENCE_FILE = DATA_DIR / "confidence_state.json"
NODES_FILE = DATA_DIR / "nodes.json"
BINDINGS_FILE = DATA_DIR / "bindings.json"

CONTROLLER_URL = "http://127.0.0.1:21909"

# 大区映射对照表
REGION_MAP = {
    "US": "NA", "CA": "NA", "MX": "NA",
    "GB": "EU", "FR": "EU", "DE": "EU", "IT": "EU", "ES": "EU", "NL": "EU", "CH": "EU", "DK": "EU", "RO": "EU",
    "JP": "EA", "KR": "EA", "TW": "EA", "HK": "EA", "MO": "EA", "CN": "EA",
    "SG": "SEA", "MY": "SEA", "ID": "SEA", "TH": "SEA", "VN": "SEA", "PH": "SEA",
    "AU": "OC", "NZ": "OC",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def get_region(country_code: str) -> str:
    if not country_code:
        return "UNKNOWN"
    return REGION_MAP.get(str(country_code).upper().strip(), "UNKNOWN")


def read_controller_secret() -> str:
    """从 config.yaml 解析 controller secret。"""
    try:
        content = CONFIG_PATH.read_text(encoding="utf-8")
        m = re.search(r'secret:\s*["\']?([^"\'\r\n]+)', content)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return ""


def call_mihomo_api(endpoint: str, method: str = "GET", body: Optional[dict] = None, timeout: float = 8.0) -> Any:
    """安全调用本地 Mihomo 控制器 API。"""
    url = f"{CONTROLLER_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    secret = read_controller_secret()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        res_data = resp.read()
        if res_data:
            return json.loads(res_data.decode("utf-8"))
        return None


def probe_google_country(port: int, timeout: float = 6.0) -> str:
    """通过本地 SOCKS5 端口实测 Google Terms Country version。"""
    cmd = [
        "curl.exe", "-s", "-L", "--max-time", str(int(timeout)),
        "--socks5-hostname", f"127.0.0.1:{port}",
        "https://policies.google.com/terms"
    ]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 3, creationflags=0x08000000)
        body = cp.stdout or ""
        m = re.search(r"Country version:</a>\s*([^<]+)", body, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m2 = re.search(r"country-version.*?([A-Za-z ]+)</p>", body, re.IGNORECASE)
        if m2:
            return m2.group(1).strip()
        if "policies.google.com" in body:
            return "Unknown"
    except Exception:
        pass
    return "FAIL"


def send_local_notification(text: str, emote: str = "work", motion: str = "wiggle") -> bool:
    """通过鲸管家发送自愈气泡通知。"""
    try:
        from .jingguanjia_notify import announce
        return announce(text, emote=emote, motion=motion)
    except Exception:
        pass
    return False


def append_repair_event(event_type: str, details: Dict[str, Any], severity: str = "notice") -> None:
    """落盘自愈审计事件。"""
    OPERATIONS_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "event_id": f"heal_{int(time.time()*1000)}",
        "timestamp": utc_now(),
        "type": event_type,
        "severity": severity,
        "details": details,
    }
    with open(REPAIR_EVENTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def get_current_port_proxy(port: int, config_file: Optional[Path] = None) -> Optional[str]:
    """读取指定端口当前在 config.yaml 中指向的 proxy 名称。"""
    cfg = config_file or CONFIG_PATH
    if not cfg.exists():
        return None
    lines = cfg.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if re.search(rf'name:\s*in-{port}\b', line):
            for j in range(i, min(len(lines), i + 8)):
                m = re.search(r'proxy:\s*([^\s#]+)', lines[j])
                if m:
                    return m.group(1).strip()
    return None


def select_candidate_node(port: int, current_proxy: Optional[str] = None) -> Dict[str, Any]:
    """根据大区合规与置信度引擎选择最优候选节点。
    
    规则：
    1. 必须排除当前出故障的旧节点和该端口自身；
    2. 坚决排除被一票否决（送中、离线、大区禁用）的节点；
    3. 同国优先，其次同大区（严禁跨大区漂移）；
    4. 评分从高到低（S/A级优先），延迟从低到高。
    """
    confidence_data = {}
    if CONFIDENCE_FILE.exists():
        try:
            confidence_data = json.loads(CONFIDENCE_FILE.read_text(encoding="utf-8")).get("ports", {})
        except Exception:
            pass

    # 确定目标端口的历史基线大区与国家
    port_rec = confidence_data.get(str(port), {})
    baseline_cc = port_rec.get("baselineCountry") or (port_rec.get("lastProbe") or {}).get("country") or ""
    baseline_region = get_region(baseline_cc)

    # 从 Mihomo 获取所有现役 proxies
    try:
        api_proxies = call_mihomo_api("proxies").get("proxies", {})
    except Exception:
        api_proxies = {}

    candidates: List[Dict[str, Any]] = []

    for name, info in api_proxies.items():
        # 排除特殊组与系统节点
        if name in {"DIRECT", "REJECT", "GLOBAL", "COMPATIBLE", "PASS", "PASS-RULE", "ALL", "AUTO-POOL"}:
            continue
        if info.get("type") not in {"Shadowsocks", "Vmess", "Trojan", "AnyTLS", "Hysteria2", "Vless"}:
            continue
        if current_proxy and name == current_proxy:
            continue

        # 解析该 proxy 对应的端口号（如 xc-22004 -> 22004, fw-21012 -> 21012）
        m_p = re.search(r'(\d{5})', name)
        p_num = int(m_p.group(1)) if m_p else None
        if p_num == port:
            continue

        c_rec = confidence_data.get(str(p_num), {}) if p_num else {}
        
        # 一票否决检查
        if c_rec.get("vetoed"):
            continue
        
        last_probe = c_rec.get("lastProbe") or {}
        g_country = last_probe.get("googleCountry") or ""
        if g_country.lower() == "china":
            continue

        cand_cc = last_probe.get("country") or c_rec.get("baselineCountry") or ""
        cand_region = get_region(cand_cc)

        score = float(c_rec.get("score") or 0.0)
        tier = c_rec.get("tier") or "B"
        latency = (info.get("history") or [{}])[-1].get("delay") or last_probe.get("latency_ms") or 9999

        candidates.append({
            "name": name,
            "port": p_num,
            "country": cand_cc,
            "region": cand_region,
            "google_country": g_country,
            "score": score,
            "tier": tier,
            "latency": latency,
            "is_same_country": bool(baseline_cc and cand_cc and baseline_cc.upper() == cand_cc.upper()),
            "is_same_region": bool(baseline_region != "UNKNOWN" and cand_region == baseline_region),
        })

    if not candidates:
        return {"ok": False, "reason": "no_candidates_found"}

    # 排序：同国优先 > 同大区优先 > 评分高优先 > 延迟低优先
    candidates.sort(key=lambda x: (
        not x["is_same_country"],
        not x["is_same_region"],
        -x["score"],
        x["latency"]
    ))

    # 如果基线有特定大区，坚决杜绝跨大区盲目指派
    selected = candidates[0]
    if baseline_region != "UNKNOWN" and not selected["is_same_region"] and not selected["is_same_country"]:
        # 降级告警：无同大区可用候选
        return {
            "ok": False,
            "reason": f"no_candidate_in_region_{baseline_region}",
            "best_cross_region": selected,
        }

    return {"ok": True, "candidate": selected, "total_considered": len(candidates)}


def hot_swap_port_node(port: int, new_proxy_name: str, reason: str = "autonomous_healing") -> Dict[str, Any]:
    """对指定端口在底层执行物理节点热替换。
    
    1. 备份 config.yaml；
    2. 精确替换 in-<port> 与 in-http-<port> 的 proxy 字段；
    3. 调用 PUT /configs?force=true 热重载；
    4. 实测端口验证（TCP连通 + Google判定非China）；
    5. 若验证失败自动回滚；若成功落盘审计日志并发送通知。
    """
    if not CONFIG_PATH.exists():
        return {"ok": False, "error": f"config_not_found: {CONFIG_PATH}"}

    # 1. 备份配置
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_file = BACKUP_DIR / f"config.yaml.bak-{ts}-port{port}"
    shutil.copy2(CONFIG_PATH, backup_file)

    # 2. 修改配置
    lines = CONFIG_PATH.read_text(encoding="utf-8").splitlines()
    modified = False
    old_proxy = None

    for i, line in enumerate(lines):
        if re.search(rf'name:\s*(in-{port}|in-http-{port})\b', line):
            for j in range(i, min(len(lines), i + 8)):
                m = re.search(r'proxy:\s*([^\s#]+)', lines[j])
                if m:
                    if not old_proxy:
                        old_proxy = m.group(1).strip()
                    lines[j] = re.sub(r'proxy:\s*[^\s#]+', f'proxy: {new_proxy_name}', lines[j])
                    modified = True

    if not modified:
        return {"ok": False, "error": f"port_{port}_listeners_not_found_in_config"}

    # 原子写入新配置
    temp_path = CONFIG_PATH.with_suffix(".tmp")
    temp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp_path.replace(CONFIG_PATH)

    # 3. 热重载 Mihomo
    try:
        call_mihomo_api("configs?force=true", method="PUT", body={"path": str(CONFIG_PATH.resolve())})
        time.sleep(1.0)
    except Exception as exc:
        # 重载异常立即回滚
        shutil.copy2(backup_file, CONFIG_PATH)
        return {"ok": False, "error": f"mihomo_hot_reload_failed: {exc}", "rolled_back": True}

    # 4. 现场复核新出口
    verified_country = probe_google_country(port, timeout=8.0)
    if verified_country.lower() == "china" or verified_country == "FAIL":
        # 换上去依然送中或断网，立即回滚
        shutil.copy2(backup_file, CONFIG_PATH)
        call_mihomo_api("configs?force=true", method="PUT", body={"path": str(CONFIG_PATH.resolve())})
        append_repair_event("heal_failed_rollback", {
            "port": port,
            "tried_proxy": new_proxy_name,
            "old_proxy": old_proxy,
            "reason": reason,
            "verified_country": verified_country,
        }, severity="action_required")
        return {
            "ok": False,
            "error": f"post_probe_unhealthy: google_country={verified_country}",
            "rolled_back": True,
        }

    # 5. 成功审计留痕与状态同步写回
    event_payload = {
        "port": port,
        "old_proxy": old_proxy,
        "new_proxy": new_proxy_name,
        "reason": reason,
        "verified_google_country": verified_country,
        "backup_path": str(backup_file),
    }
    append_repair_event("heal_success", event_payload, severity="notice")

    # 关键修复：换绑成功后必须原子写回 confidence_state.json，清除 vetoed 状态，防止下一轮巡检死循环重复换绑！
    try:
        if CONFIDENCE_FILE.exists():
            c_data = json.loads(CONFIDENCE_FILE.read_text(encoding="utf-8"))
            p_str = str(port)
            if "ports" in c_data and p_str in c_data["ports"]:
                rec = c_data["ports"][p_str]
                rec["vetoed"] = False
                rec["vetoReason"] = ""
                rec["offline"] = False
                rec["score"] = 85.0
                rec["currentProxy"] = new_proxy_name
                rec["lastHealedTime"] = time.time()
                if "lastProbe" not in rec or not isinstance(rec["lastProbe"], dict):
                    rec["lastProbe"] = {}
                rec["lastProbe"]["googleCountry"] = verified_country
                rec["lastProbe"]["timestamp"] = time.time()
                CONFIDENCE_FILE.write_text(json.dumps(c_data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    # 取消内部单次换绑通知刷屏，避免批量换绑时连续轰炸微信
    # notify_msg = (...)
    # send_local_notification(...)

    return {
        "ok": True,
        "port": port,
        "old_proxy": old_proxy,
        "new_proxy": new_proxy_name,
        "verified_country": verified_country,
        "backup_path": str(backup_file),
    }


def auto_heal_port(port: int, reason: str = "auto_detect") -> Dict[str, Any]:
    """为指定端口全自动决策并完成热替换自愈。"""
    current_proxy = get_current_port_proxy(port)
    res = select_candidate_node(port, current_proxy=current_proxy)
    if not res.get("ok"):
        append_repair_event("heal_blocked", {
            "port": port,
            "current_proxy": current_proxy,
            "reason": res.get("reason"),
        }, severity="action_required")
        return {"ok": False, "error": res.get("reason"), "port": port}

    candidate = res["candidate"]
    return hot_swap_port_node(port, candidate["name"], reason=reason)


def scan_and_heal_all(scope: str = "bound") -> List[Dict[str, Any]]:
    """全自动巡检扫描并自愈所有送中或离线的一票否决端口。"""
    if not CONFIDENCE_FILE.exists():
        return []
    try:
        conf = json.loads(CONFIDENCE_FILE.read_text(encoding="utf-8")).get("ports", {})
    except Exception:
        return []

    results = []
    for port_str, rec in conf.items():
        try:
            port = int(port_str)
        except ValueError:
            continue

        # 检查是否触发自愈条件：被一票否决、离线或最近一次实测为 China
        last_probe = rec.get("lastProbe") or {}
        g_country = str(last_probe.get("googleCountry") or "").lower()
        veto_reason = rec.get("vetoReason") or ""

        # 防震荡冷却门禁：若距离上次换绑不足 3600 秒 (1小时)，跳过，坚决防止 A <-> B 频繁来回横跳！
        last_healed = float(rec.get("lastHealedTime") or 0.0)
        if time.time() - last_healed < 3600.0:
            continue

        needs_heal = False
        reason = ""
        if g_country == "china" or veto_reason == "sent_to_china":
            needs_heal = True
            reason = "sent_to_china"
        elif rec.get("offline") or veto_reason == "offline":
            needs_heal = True
            reason = "node_offline"

        if needs_heal:
            heal_res = auto_heal_port(port, reason=reason)
            results.append(heal_res)

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AgentProxyHub 节点热替换与自愈执行器")
    parser.add_argument("--port", type=int, help="目标端口号")
    parser.add_argument("--proxy", type=str, help="指定替换的目标节点名 (如 xc-22004)")
    parser.add_argument("--auto", action="store_true", help="自动推荐候选并执行热替换")
    parser.add_argument("--scan", action="store_true", help="全量扫描送中或失效端口并自愈")
    args = parser.parse_args()

    if args.scan:
        healed = scan_and_heal_all()
        print(json.dumps(healed, ensure_ascii=False, indent=2))
    elif args.port and args.proxy:
        res = hot_swap_port_node(args.port, args.proxy)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.port and args.auto:
        res = auto_heal_port(args.port)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        parser.print_help()
