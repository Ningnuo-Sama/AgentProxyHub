#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentProxyHub 节点时序置信度引擎 (Phase 1)

与 data/nodes.json 的分工：
- nodes.json：静态测绘快照（单次体检结论：送中标记、Google 判定国、S/A/F 评级），由巡检引擎维护。
- confidence_state.json（本引擎产出）：时序观察账本——出口漂移史、观察钟、延迟样本、加权置信分。

设计要点（对应 2026-09-30 方案评审结论）：
- 三维加权：物理稳定性 40% / 大区合规 30% / 协议健康 30%（协议质量与业务履约合并，避免双重惩罚）。
- 分段观察期：24h 解锁备选资格（基础分 60）、48h 候选优先（80）、72h S 级置信（100）。
- 分级漂移判定：洲际漂移 = 一票否决 + 7 天禁用；同大区跨国 -30 分并重置观察钟为 48h；同国换 IP -10 分。
- 一票否决：送中（isSentToChina）／离线／洲际漂移未满禁用期 → 总分直接 0（F 级）。
- 只产出建议与评分，绝不自动改绑任何端口：老号粘性保护由上层决策（Agent/人工）负责。

用法：
  python core/confidence_engine.py --scope bound   # 现役绑定端口 + S/A 级（日常巡检，默认）
  python core/confidence_engine.py --scope all     # 全量 125 端口
  python core/confidence_engine.py --port 21050 22002
  python core/confidence_engine.py --show          # 只读展示当前快照
"""

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("APHUB_DATA_DIR") or os.path.join(ROOT, "data")
NODES_FILE = os.path.join(DATA_DIR, "nodes.json")
STATE_FILE = os.path.join(DATA_DIR, "confidence_state.json")

MAX_SAMPLES = 24            # 每端口保留的延迟样本上限（约 2 天 × 12 次巡检）
VETO_BAN_DAYS = 7           # 洲际漂移禁用期
W_STABILITY, W_COMPLIANCE, W_HEALTH = 0.40, 0.30, 0.30

# 大洲分区（覆盖池内出现过的国家；未收录的国家归入 "other"，跨组漂移按洲际处理）
_CONTINENTS = {
    "europe": {"GB", "DE", "FR", "NL", "CH", "ES", "IT", "SE", "NO", "FI", "DK", "AT",
               "PL", "CZ", "HU", "RO", "BG", "UA", "BY", "LT", "LV", "EE", "IS", "IE",
               "PT", "GR", "SI", "HR", "SK", "MK", "RS", "BA", "MD", "CY", "MT", "LU"},
    "americas_n": {"US", "CA"},
    "americas_s": {"MX", "BR", "AR", "CL", "CO", "PE", "EC", "UY", "PY", "BO", "VE",
                   "PA", "CR", "GT", "DO", "JM", "BS"},
    "asia": {"JP", "KR", "TW", "HK", "SG", "MY", "TH", "VN", "PH", "ID", "IN", "PK",
             "BD", "KZ", "KG", "UZ", "AZ", "GE", "AM", "TR", "AE", "SA", "IL", "QA",
             "BH", "OM", "KW", "JO", "LB", "IQ", "IR", "CN"},
    "africa": {"ZA", "EG", "NG", "MA", "DZ", "TN", "KE", "GH", "ET", "TZ"},
    "oceania": {"AU", "NZ", "FJ"},
}

def continent_of(cc: Optional[str]) -> str:
    if not cc:
        return "unknown"
    cc = cc.upper()
    for name, members in _CONTINENTS.items():
        if cc in members:
            return name
    return "other"

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def hours_since(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        t = dt.datetime.fromisoformat(iso)
        return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600.0
    except ValueError:
        return None

# ---------------------------------------------------------------- 探测

def probe_google_country(port: int, timeout: float = 8.0) -> str:
    """通过代理读取 Google 自己的 Country version；这是账号风控相关的首要国家信号。"""
    cmd = ["curl.exe", "-s", "--max-time", str(int(timeout)),
           "-x", f"socks5h://127.0.0.1:{port}",
           "https://policies.google.com/terms"]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            creationflags=0x08000000, timeout=timeout + 3)
        body = cp.stdout or ""
        import re
        m = re.search(r"Country version:</a>\s*([^<]+)", body, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        if "policies.google.com" in body:
            return "Unknown"
    except Exception:
        pass
    return "FAIL"


def probe_port(port: int, timeout: float = 10.0) -> Dict[str, Any]:
    """实测一个本地 SOCKS5 端口：物理 IP/国家 + Google 自判国家 + 总耗时。

    Google 自判国家用于账号身份决策；ipwho/api-ipify 只作为物理网络与漂移辅助。
    返回 {"ok", "ip", "country", "google_country", "latency_ms", "error"}。
    """
    def _curl(url: str) -> Tuple[int, str]:
        cmd = ["curl.exe", "-s", "--max-time", str(int(timeout)),
               "-x", f"socks5h://127.0.0.1:{port}",
               "-w", "\n%{time_total}", url]
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True,
                                creationflags=0x08000000, timeout=timeout + 5)
            return cp.returncode, cp.stdout.strip()
        except Exception:
            return 1, ""

    rc, body = _curl("https://ipwho.is/")
    if rc == 0 and body:
        lines = body.rsplit("\n", 1)
        try:
            latency_ms = int(float(lines[1]) * 1000)
        except (IndexError, ValueError):
            latency_ms = -1
        try:
            info = json.loads(lines[0])
            ip = info.get("ip") or ""
            cc = info.get("country_code") or ""
            if ip:
                return {"ok": True, "ip": ip, "country": cc.upper(),
                        "google_country": probe_google_country(port, timeout),
                        "latency_ms": latency_ms}
        except (json.JSONDecodeError, IndexError):
            pass
    # 退路：只拿 IP（国家码留空，漂移分级延后到有国码时判定）
    rc, body = _curl("https://api.ipify.org")
    if rc == 0 and body and "\n" in body:
        lines = body.rsplit("\n", 1)
        try:
            latency_ms = int(float(lines[1]) * 1000)
        except (IndexError, ValueError):
            latency_ms = -1
        ip = lines[0].strip()
        if ip and len(ip) <= 45:
            return {"ok": True, "ip": ip, "country": "",
                    "google_country": probe_google_country(port, timeout),
                    "latency_ms": latency_ms}
    return {"ok": False, "ip": "", "country": "", "latency_ms": -1, "error": "probe_failed"}

# ---------------------------------------------------------------- 打分

def stability_score(rec: Dict[str, Any]) -> float:
    """物理稳定性（40%）：观察钟分段 24h→60 / 48h→80 / 72h→100；漂移史扣分。"""
    hours = hours_since(rec.get("stableSince")) or 0.0
    if hours >= 72:
        base = 100.0
    elif hours >= 48:
        base = 80.0
    elif hours >= 24:
        base = 60.0
    elif hours >= 6:
        base = 40.0
    else:
        base = 20.0
    penalty = rec.get("driftPenalty", 0)   # 最近一次漂移的遗留扣分，随时间线性衰减
    return max(0.0, base - penalty)

def compliance_score(node: Optional[Dict[str, Any]]) -> float:
    """大区合规（30%）：直接采用静态测绘结论（Google 判定国 + Flow 支持 + 送中标记）。"""
    if not node:
        return 30.0   # 无测绘数据，给保守底分
    if node.get("isSentToChina"):
        return 0.0
    if node.get("flowSupported"):
        return 100.0
    gc = (node.get("googleCountry") or "").strip()
    if gc in ("Unknown", "-", ""):
        return 20.0
    return 40.0   # 冷门非支持区

def health_score(rec: Dict[str, Any]) -> float:
    """协议健康（30%）：近端延迟样本，<500ms 满分，线性衰减到 1500ms 归零。"""
    samples = [s["latency_ms"] for s in rec.get("samples", []) if s.get("latency_ms", 0) > 0]
    if not samples:
        return 30.0   # 样本不足给保守底分
    recent = samples[-6:]           # 近 6 个样本
    avg = sum(recent) / len(recent)
    if avg <= 500:
        return 100.0
    if avg >= 1500:
        return 0.0
    return 100.0 * (1500.0 - avg) / 1000.0

def classify_drift(baseline_cc: str, new_cc: str) -> str:
    """分级漂移判定：cross_continent / cross_country_same_region / same_country / unknown"""
    if not baseline_cc or not new_cc:
        return "unknown"
    if baseline_cc == new_cc:
        return "same_country"
    if continent_of(baseline_cc) != continent_of(new_cc):
        return "cross_continent"
    return "cross_country_same_region"

def tier_of(score: float, vetoed: bool) -> str:
    if vetoed or score < 40:
        return "F"
    if score >= 85:
        return "S"
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    return "C"

# ---------------------------------------------------------------- 主流程

def load_nodes_index() -> Dict[int, Dict[str, Any]]:
    if not os.path.exists(NODES_FILE):
        return {}
    try:
        with open(NODES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {n["port"]: n for n in data.get("nodes", []) if "port" in n}
    except Exception:
        return {}

def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"updatedAt": None, "ports": {}}

def save_state(state: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)

def update_record(port: int, probe: Dict[str, Any], node: Optional[Dict[str, Any]],
                  rec: Dict[str, Any]) -> Dict[str, Any]:
    """把一次探测结果并入时序记录；Google 自判国家优先，物理国家仅作辅助。"""
    now = now_iso()
    google_country = (probe.get("google_country") or "").strip().upper()
    physical_country = (probe.get("country") or "").strip().upper()
    baseline_ip = rec.get("baselineIp") or ""
    baseline_cc = rec.get("baselineGoogleCountry") or rec.get("baselineCountry") or ""
    if not baseline_ip:
        baseline_ip = (node or {}).get("ip") or ""
    if baseline_ip and not rec.get("baselineIp"):
        rec["baselineIp"] = baseline_ip
    if not baseline_cc:
        baseline_cc = ((node or {}).get("googleCountry") or (node or {}).get("countryCode") or "").strip().upper()
    if baseline_cc and not rec.get("baselineCountry"):
        rec["baselineCountry"] = baseline_cc

    rec.setdefault("samples", [])
    rec.setdefault("driftEvents", [])

    if not probe.get("ok"):
        rec["consecutiveFailures"] = rec.get("consecutiveFailures", 0) + 1
        rec["lastProbe"] = {"t": now, "ok": False}
        # 连续 3 次失败 → 视为离线（一票否决），但不抹历史观察钟，恢复后可继续
        rec["offline"] = rec["consecutiveFailures"] >= 3
    else:
        rec["consecutiveFailures"] = 0
        rec["offline"] = False
        rec["lastProbe"] = {"t": now, "ok": True, "ip": probe["ip"],
                            "country": probe["country"],
                            "googleCountry": probe.get("google_country") or "FAIL"}
        if probe["latency_ms"] > 0:
            rec["samples"].append({"t": now, "latency_ms": probe["latency_ms"]})
            rec["samples"] = rec["samples"][-MAX_SAMPLES:]

        # 漂移检测：与基线（首次见到的稳定 IP / 测绘 IP）比对
        current_ip = probe["ip"]
        effective_cc = google_country if google_country not in ("", "FAIL", "UNKNOWN") else physical_country
        if not baseline_ip:
            baseline_ip = current_ip
            rec["baselineIp"] = current_ip
        if not rec.get("baselineCountry") and baseline_cc:
            rec["baselineCountry"] = baseline_cc
        if not rec.get("baselineGoogleCountry") and google_country not in ("", "FAIL", "UNKNOWN"):
            rec["baselineGoogleCountry"] = google_country
        if not rec.get("baselinePhysicalCountry") and physical_country:
            rec["baselinePhysicalCountry"] = physical_country
        if not rec.get("stableSince"):
            rec["stableSince"] = now
        if current_ip != baseline_ip:
            drift = classify_drift(baseline_cc, effective_cc)
            if drift == "unknown":
                rec.setdefault("driftEvents", []).append({"t": now, "from": baseline_ip, "to": current_ip,
                    "kind": "unknown", "fromCc": baseline_cc, "toCc": effective_cc})
                rec["driftEvents"] = rec["driftEvents"][-20:]
                rec["lastDriftUnknown"] = True
            else:
                rec["lastDriftUnknown"] = False
            event = {"t": now, "from": baseline_ip, "to": current_ip,
                     "kind": drift, "fromCc": baseline_cc, "toCc": effective_cc}
            rec["driftEvents"].append(event)
            rec["driftEvents"] = rec["driftEvents"][-20:]
            if drift == "same_country":
                rec["driftPenalty"] = 10
                rec["stableSince"] = now
            elif drift == "cross_country_same_region":
                rec["driftPenalty"] = 30
                rec["stableSince"] = now
            elif drift == "cross_continent":
                rec["vetoUntil"] = (dt.datetime.now(dt.timezone.utc)
                                    + dt.timedelta(days=VETO_BAN_DAYS)).isoformat(timespec="seconds")
                rec["stableSince"] = now
                rec["driftPenalty"] = 0
            # unknown 只记录证据，不触发跨洲禁用，也不改变有效国家基线。
            if drift != "unknown":
                rec["baselineIp"] = current_ip
                rec["baselineCountry"] = effective_cc or baseline_cc
                if google_country not in ("", "FAIL", "UNKNOWN"):
                    rec["baselineGoogleCountry"] = google_country
                if physical_country:
                    rec["baselinePhysicalCountry"] = physical_country
        else:
            # 出口回归基线，遗留扣分随稳定时长线性衰减（48h 清零）
            hours = hours_since(rec.get("stableSince")) or 0.0
            p0 = rec.get("driftPenalty", 0)
            rec["driftPenalty"] = max(0.0, p0 * (1 - hours / 48.0)) if p0 else 0.0

    # ---- 计算总分 ----
    vetoed = bool(rec.get("offline")) or bool(node and node.get("isSentToChina"))
    ban_left = hours_since(rec.get("vetoUntil")) or 0.0
    if rec.get("vetoUntil") and ban_left < 0:
        vetoed = True   # 洲际漂移禁用期未满（hours_since 为负表示尚未到期）

    s = stability_score(rec) * W_STABILITY
    c = compliance_score(node) * W_COMPLIANCE
    h = health_score(rec) * W_HEALTH
    rec["score"] = 0.0 if vetoed else round(s + c + h, 1)
    rec["tier"] = tier_of(rec["score"], vetoed)
    rec["vetoed"] = vetoed
    rec["vetoReason"] = ("offline" if rec.get("offline")
                         else "sent_to_china" if node and node.get("isSentToChina")
                         else "cross_continent_ban" if vetoed else "")
    rec["observeHours"] = round(hours_since(rec.get("stableSince")) or 0.0, 1)
    rec["updatedAt"] = now
    return rec

def select_ports(scope: str, explicit: List[int]) -> List[int]:
    nodes = load_nodes_index()
    if explicit:
        return [p for p in explicit if p in nodes] or explicit
    if scope == "all":
        return sorted(nodes)
    # bound：现役绑定端口（bindings.json）+ S/A 级静态节点
    ports = set()
    try:
        with open(os.path.join(DATA_DIR, "bindings.json"), "r", encoding="utf-8") as f:
            for v in json.load(f).values():
                p = v.get("port") if isinstance(v, dict) else None
                if p:
                    ports.add(int(p))
    except Exception:
        pass
    for p, n in nodes.items():
        if n.get("healthRating") in ("S", "A") and not n.get("isSentToChina"):
            ports.add(p)
    return sorted(ports)

def run(scope: str, explicit: List[int], max_workers: int = 8) -> Dict[str, Any]:
    nodes = load_nodes_index()
    state = load_state()
    ports = select_ports(scope, explicit)
    print(f"[confidence] 探测 {len(ports)} 个端口 (scope={scope or 'port'}) ...")
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(probe_port, p): p for p in ports}
        for fut in concurrent.futures.as_completed(futures):
            port = futures[fut]
            probe = fut.result()
            rec = state["ports"].setdefault(str(port), {})
            update_record(port, probe, nodes.get(port), rec)
            flag = "" if probe.get("ok") else " (探测失败)"
            print(f"  {port}: {rec.get('tier')} {rec.get('score'):>5} | "
                  f"{probe.get('ip', '-'):<16} {probe.get('country', '-') or '-':<3} | "
                  f"obs={rec.get('observeHours')}h{flag}")
    state["updatedAt"] = now_iso()
    save_state(state)
    print(f"[confidence] 完成，耗时 {time.time()-t0:.0f}s → {STATE_FILE}")
    return state

def show() -> None:
    state = load_state()
    if not state.get("ports"):
        print("[confidence] 尚无快照，请先运行一次巡检")
        return
    print(f"快照时间: {state.get('updatedAt')}")
    rows = sorted(state["ports"].items(), key=lambda kv: -kv[1].get("score", 0))
    print(f"{'port':<7}{'tier':<5}{'score':<7}{'obs(h)':<8}{'IP':<17}{'CC':<4}flags")
    for port, r in rows:
        ip = (r.get("lastProbe") or {}).get("ip", "-")
        cc = (r.get("lastProbe") or {}).get("country", "") or (r.get("baselineCountry") or "")
        flags = ",".join(filter(None, [r.get("vetoReason") or "",
                                       "drift" if r.get("driftPenalty") else ""]))
        print(f"{port:<7}{r.get('tier'):<5}{r.get('score'):<7}{r.get('observeHours'):<8}"
              f"{ip:<17}{cc:<4}{flags}")

def main():
    ap = argparse.ArgumentParser(description="AgentProxyHub 节点置信度引擎")
    ap.add_argument("--scope", choices=["bound", "all"], default="bound")
    ap.add_argument("--port", type=int, nargs="*")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    if args.show:
        show()
        return
    run(args.scope, args.port or [])

if __name__ == "__main__":
    main()
