#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AgentProxyHub 底层节点热替换与自愈执行器 (Hot Swap Executor).

核心契约（铁律）：
1. 粘性端口神圣不可侵犯：业务层（Antigravity、Flow-Tools、指纹浏览器）绑定的本地端口永远不变。
2. 只换节点，不换端口：当端口底层物理节点失效、离线或“送中”（Google 判定国命中
   中国／香港／澳门，唯一判定入口见 core/blocked_regions.py）时，
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
from typing import Any, Dict, List, Optional, Set, Tuple

try:  # 包内导入（MCP / 调度器调用路径）
    from .blocked_regions import is_blocked_google_country
    from .process_control_lock import process_control_lock
except ImportError:  # 允许以脚本方式直接运行
    from blocked_regions import is_blocked_google_country
    from process_control_lock import process_control_lock

# t42（P2-19 L2）：热替换前置闸。**拒绝即不换**（fail-closed），不是「换了再报」。
# 判据与 MCP 侧 `mcp/server.py::_gate_precheck_bindings` 完全一致（同一批 write_guard 门禁 +
# ledger_watch.check_bind_allowed 的 G4/G5 密度），避免「两条路径两套口径」。
try:  # 包内导入
    from .write_guard import (WriteRefused, refuse_cross_region_jump, refuse_dead_account,
                              refuse_missing_contract)
except ImportError:  # 允许以脚本方式直接运行
    from write_guard import (WriteRefused, refuse_cross_region_jump, refuse_dead_account,
                             refuse_missing_contract)

# t42：`write_guard.region_of` 只认 ISO-2（"US"→NA），而 `confidence_state` 的 `lastProbe.googleCountry`
# 是 Google 页面里的**全名**（"United States"）。直接把全名喂进去会得到 region=UNKNOWN，
# 于是「同国」被判成「跨洲未知」而误拒（本文件 t42 首轮接线实测即踩中：21013 US→fw-21010 US 被拒）。
# 因此这里统一过一遍本模块既有的权威归一化 `normalize_cc`（其 docstring 记录了 2026-10-12 同类事故），
# 与 ledger_watch._check_contract_triple 的做法保持一致。


def _cc(value: Any) -> str:
    """国家值归一化为 ISO-2（全名 → 代码；空/未知 → 空串）。"""
    try:
        return str(normalize_cc(value) or "").strip().upper()
    except Exception:
        return str(value or "").strip().upper()

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


# 国家全名 / 别名 → ISO 2 码归一化表。
# confidence_state.json 的 baselineCountry 历史上存的是全名（如 "UNITED STATES"），
# 而 lastProbe.country 存 ISO 码（如 "US"），直接比较永远不相等，
# 曾导致同国/同大区优先与跨大区拦截整体失效（2026-10-12 体检修复）。
_COUNTRY_NAME_TO_ISO = {
    "UNITED STATES": "US", "USA": "US", "U.S.": "US", "AMERICA": "US",
    "UNITED KINGDOM": "GB", "UK": "GB", "ENGLAND": "GB",
    "SOUTH KOREA": "KR", "KOREA": "KR", "REPUBLIC OF KOREA": "KR",
    "TAIWAN": "TW", "TAIWAN, PROVINCE OF CHINA": "TW",
    "HONG KONG": "HK", "MACAO": "MO", "MACAU": "MO",
    "INDONESIA": "ID", "MALAYSIA": "MY", "SINGAPORE": "SG", "THAILAND": "TH",
    "VIETNAM": "VN", "PHILIPPINES": "PH",
    "GERMANY": "DE", "FRANCE": "FR", "ITALY": "IT", "SPAIN": "ES",
    "NETHERLANDS": "NL", "SWITZERLAND": "CH", "DENMARK": "DK", "ROMANIA": "RO",
    "JAPAN": "JP", "CANADA": "CA", "MEXICO": "MX",
    "AUSTRALIA": "AU", "NEW ZEALAND": "NZ",
    "UKRAINE": "UA", "RUSSIA": "RU", "INDIA": "IN", "BRAZIL": "BR",
    "COLOMBIA": "CO", "NIGERIA": "NG", "TURKEY": "TR", "ARGENTINA": "AR",
    "CHINA": "CN", "MAINLAND CHINA": "CN",
}


def normalize_cc(value: Any) -> str:
    """把国家字段（ISO 码或英文全名）归一化为 ISO 2 码，未知返回原值大写。"""
    text = str(value or "").strip().upper()
    if not text:
        return ""
    return _COUNTRY_NAME_TO_ISO.get(text, text)


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
    """通过本地 SOCKS5 端口实测 Google Terms Country version（纯 Python，零黑窗）。

    黑窗根因治理 (2026-10-12)：原实现用 subprocess 拉起 curl.exe，会派生控制台窗口；
    本机默认控制台宿主为 Windows Terminal 时即为可见黑窗。现改为 core.net_probe
    进程内 SOCKS5+TLS 直连，物理上不产生任何子进程。
    """
    try:
        from core.net_probe import probe_google_country_direct
    except ImportError:
        try:
            from net_probe import probe_google_country_direct
        except ImportError:
            return "FAIL"
    try:
        return probe_google_country_direct(port, timeout) or "FAIL"
    except Exception:
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

    # 确定目标端口的历史基线大区与国家（基线可能是全名，统一归一化为 ISO 码）
    port_rec = confidence_data.get(str(port), {})
    baseline_cc = normalize_cc(port_rec.get("baselineCountry")
                               or (port_rec.get("lastProbe") or {}).get("country") or "")
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
        if is_blocked_google_country(g_country):
            continue

        cand_cc = normalize_cc(last_probe.get("country") or c_rec.get("baselineCountry") or "")
        # 从未测绘、无任何国家记录的节点不进入候选（避免盲选未知出口）
        if not cand_cc and not g_country:
            continue
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


def _gate_hot_swap(port: int, new_proxy_name: str, reason: str = "autonomous_healing") -> Optional[Dict[str, Any]]:
    """t42（L2）：`hot_swap_port_node()` 的**前置闸**。返回 `None` = 放行；返回 dict = 拒绝（调用方原样返回）。

    判据（与 MCP 侧同一批门禁，拒绝即不执行换绑）：
      1. `refuse_sticky_port_change` —— 端口号不得被改（只换底层节点）；
      2. `refuse_missing_contract` —— 该口无 `expectedCountry` 契约 → fail-closed；
      3. `refuse_dead_account` —— 该口绑定的 profile 已 retired/banned → 拒绝；
      4. `refuse_cross_region_jump` —— 目标节点国 vs 契约期望国（跨洲/同区异国/锁区）一律拒绝；
      5. G4/G5 密度 —— `ledger_watch.check_bind_allowed()`：动作会使出口 live 账号数超上限 → 拒绝。
    目标国只从 `confidence_state.json` 的 `lastProbe` 读（**本地只读，0 WAN**）；
    读不到目标国时按"未知"处理：跨洲判据无法成立 → **fail-closed 拒绝**（绝不盲换）。
    """
    p = str(int(port))
    prof: Optional[str] = None
    contract: Dict[str, Any] = {}
    try:
        if BINDINGS_FILE.exists():
            with open(BINDINGS_FILE, "r", encoding="utf-8-sig") as f:
                raw = f.read().strip()
            if raw:
                entry = (json.loads(raw) or {}).get(p) or {}
                if isinstance(entry, dict):
                    prof = entry.get("profile")
                    contract = dict(entry)
    except Exception:
        pass  # 账本读失败 → contract 为空 → 下面 refuse_missing_contract 会拒绝（fail-closed）

    try:
        # 1) 粘性端口：监听器必须仍指向同一端口号
        # ⚠️ 取**该业务口自身**的监听器映射（`in-<port>` / `in-http-<port>`），
        # 不可用目标节点的 proxy 名反推端口号——同一物理出口可由多个 fw-* 节点定义共同承载
        # （例：`fw-21011` 同时服务 21010/21011/21013），反推会把 21013 误判成 21011。
        listener_port: Optional[int] = None
        proxy_now = _listener_proxy_for_port(int(port))
        if proxy_now:
            listener_port = int(port)
        if listener_port is None:
            raise WriteRefused("sticky_port", f"listener_missing: 端口 {port} 无对应监听器", {"port": int(port)})
        if listener_port != int(port):
            raise WriteRefused("sticky_port", f"port_renumbered: {port}->{listener_port}",
                               {"port": int(port), "listener_port": listener_port})

        # 2) 契约缺失 → fail-closed
        refuse_missing_contract(port=int(port), contract=contract)

        # 3) 死号不得占用受保护名额
        if prof:
            refuse_dead_account(profile=str(prof))

        # 4) 跨洲 / 锁区（目标国来自本地 confidence_state，0 WAN）
        expected = _cc(contract.get("expectedCountry"))
        target = ""
        if CONFIDENCE_FILE.exists():
            try:
                conf = json.loads(CONFIDENCE_FILE.read_text(encoding="utf-8-sig")).get("ports", {}) or {}
                t_num = re.sub(r"\D", "", str(new_proxy_name)) or ""
                t_rec = conf.get(t_num) or {}
                lp = t_rec.get("lastProbe") or {}
                # t42：全名 → ISO-2（否则 write_guard.region_of 会把它当 UNKNOWN 而误判跨洲）
                target = _cc(lp.get("googleCountry") or lp.get("country") or t_rec.get("baselineCountry"))
            except Exception:
                target = ""
        if not target:
            # 目标国未知 → 无法证明"没跨洲" → fail-closed
            raise WriteRefused("cross_region", "target_country_unknown: 目标节点无任何实测国别记录",
                               {"port": int(port), "expected": expected, "target_proxy": new_proxy_name,
                                "note": "只换已知国别节点；未知出口一律拒绝（绝不盲换）"})
        refuse_cross_region_jump(expected_country=expected, target_country=target, port=int(port))

        # 5) G4/G5 密度（0 WAN；enforce 关闭时只报告）
        try:
            from .ledger_watch import check_bind_allowed as _cba  # type: ignore
        except ImportError:
            from ledger_watch import check_bind_allowed as _cba  # type: ignore
        verdict = _cba(int(port), prof or None)
        if verdict.get("allowed") is False:
            return {"ok": False, "port": int(port), "error": f"gate_refused: {verdict.get('reason')}",
                    "refused_reason": str(verdict.get("reason")), "gate": "density_g4g5",
                    "bindings_changed": False, "config_changed": False, "gate_verdict": verdict}
    except WriteRefused as exc:
        _append_gate_refusal(port, new_proxy_name, reason, exc)
        return {"ok": False, "port": int(port), "error": f"gate_refused: {exc}",
                "refused_reason": str(getattr(exc, "reason", exc)), "gate": getattr(exc, "gate", None),
                "detail": getattr(exc, "detail", {}) or {},
                "bindings_changed": False, "config_changed": False}
    except Exception as exc:  # 闸门自身异常 → fail-closed，绝不放行
        wrapped = WriteRefused("gate_unknown_state", f"{type(exc).__name__}: {exc}",
                               {"port": int(port), "target_proxy": new_proxy_name})
        _append_gate_refusal(port, new_proxy_name, reason, wrapped)
        return {"ok": False, "port": int(port), "error": f"gate_refused: {wrapped}",
                "refused_reason": str(wrapped.reason), "gate": "gate_unknown_state",
                "detail": wrapped.detail, "bindings_changed": False, "config_changed": False}
    return None


def _append_gate_refusal(port: int, new_proxy_name: str, reason: str, exc: Exception) -> None:
    """拒绝留痕（只写本地 repair_events.jsonl，不触任何网络、不打印任何凭据）。"""
    try:
        append_repair_event("gate_refused", {
            "port": int(port),
            "target_proxy": new_proxy_name,
            "request_reason": reason,
            "gate": getattr(exc, "gate", None),
            "refused_reason": str(getattr(exc, "reason", exc))[:200],
        }, severity="action_required")
    except Exception:
        pass


def _listener_proxy_for_port(port: int) -> Optional[str]:
    """只读 `in-<port>` 当前映射的 proxy 名（供粘性端口校验）；不解析任何凭据字段。"""
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
        m = re.search(rf'name:\s*in-{int(port)}\b', text)
        if not m:
            return None
        tail = text[m.end():m.end() + 400]
        pm = re.search(r'proxy:\s*([^\s#]+)', tail)
        return pm.group(1).strip() if pm else None
    except Exception:
        return None


def hot_swap_port_node(port: int, new_proxy_name: str, reason: str = "autonomous_healing") -> Dict[str, Any]:
    """对指定端口在底层执行物理节点热替换。

    1. **t42 前置闸**：跨洲/锁区/契约缺失/密度/死号任一不过 → 拒绝并原样返回（不备份、不改配置、不热重载）；
    2. 备份 config.yaml；
    3. 精确替换 in-<port> 与 in-http-<port> 的 proxy 字段；
    4. 调用 PUT /configs?force=true 热重载；
    5. 实测端口验证（TCP连通 + Google判定非China）；
    6. 若验证失败自动回滚；若成功落盘审计日志并发送通知。
    """
    if not CONFIG_PATH.exists():
        return {"ok": False, "error": f"config_not_found: {CONFIG_PATH}"}

    # t42（P2-19 L2）：**执行前**过闸。拒绝即不换——这里在任何副作用之前。
    refused = _gate_hot_swap(port, new_proxy_name, reason=reason)
    if refused is not None:
        return refused

    # 跨进程锁：CLI --scan 与常驻 scheduler 可能同时触发换绑，
    # 并发读改写同一 config.yaml 会互相覆盖甚至写坏配置。
    with process_control_lock():
        return _hot_swap_port_node_locked(port, new_proxy_name, reason=reason)



def _hot_swap_port_node_locked(port: int, new_proxy_name: str, reason: str = "autonomous_healing") -> Dict[str, Any]:
    """在已持有控制锁的前提下执行热替换（勿直接调用，入口是 hot_swap_port_node）。"""
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
        return {"ok": False, "port": port, "error": f"port_{port}_listeners_not_found_in_config"}

    # 原子写入新配置（唯一临时名，防并发覆盖）
    temp_path = CONFIG_PATH.with_suffix(f".tmp-{os.getpid()}-{int(time.time()*1000)}")
    temp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp_path.replace(CONFIG_PATH)

    # 3. 热重载 Mihomo
    try:
        call_mihomo_api("configs?force=true", method="PUT", body={"path": str(CONFIG_PATH.resolve())})
        time.sleep(1.0)
    except Exception as exc:
        # 重载异常立即回滚
        shutil.copy2(backup_file, CONFIG_PATH)
        return {"ok": False, "port": port, "error": f"mihomo_hot_reload_failed: {exc}", "rolled_back": True}

    # 4. 现场复核新出口
    verified_country = probe_google_country(port, timeout=8.0)
    if is_blocked_google_country(verified_country) or verified_country == "FAIL":
        # 换上去依然送中或断网，立即回滚
        shutil.copy2(backup_file, CONFIG_PATH)
        try:
            call_mihomo_api("configs?force=true", method="PUT", body={"path": str(CONFIG_PATH.resolve())})
        except Exception as rollback_exc:
            # 回滚重载失败必须显式暴露：磁盘已是旧配置但内核可能仍跑新配置
            append_repair_event("rollback_reload_failed", {
                "port": port,
                "tried_proxy": new_proxy_name,
                "old_proxy": old_proxy,
                "reason": reason,
                "verified_country": verified_country,
                "rollback_error": str(rollback_exc),
            }, severity="critical")
            return {
                "ok": False,
                "port": port,
                "error": f"rollback_reload_failed: {rollback_exc}",
                "rolled_back": True,
                "manual_intervention_required": True,
            }
        append_repair_event("heal_failed_rollback", {
            "port": port,
            "tried_proxy": new_proxy_name,
            "old_proxy": old_proxy,
            "reason": reason,
            "verified_country": verified_country,
        }, severity="action_required")
        return {
            "ok": False,
            "port": port,
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

def get_protected_bound_ports() -> Set[int]:
    """获取所有在用绑定的保护端口集合（bindings.json + Antigravity粘性端口）。"""
    bound_ports = set()
    try:
        if BINDINGS_FILE.exists():
            with open(BINDINGS_FILE, "r", encoding="utf-8-sig") as f:
                content = f.read().strip()
                if content:
                    for k, v in json.loads(content).items():
                        # bindings.json 条目形如 {"21013": {...}}：端口是 JSON 键；
                        # 兼容历史/异形条目里显式存放的 "port" 字段作为回退。
                        p = None
                        try:
                            p = int(str(k).strip())
                        except (TypeError, ValueError):
                            p = None
                        if p is None and isinstance(v, dict):
                            p = v.get("port")
                        if p:
                            bound_ports.add(int(p))
    except Exception:
        pass
    antigravity_ports = {21010, 21012, 21014, 22002, 22010, 22021, 22023, 22024, 22038}
    return bound_ports | antigravity_ports


def scan_and_heal_all(scope: str = "bound") -> List[Dict[str, Any]]:
    """全自动巡检扫描并自愈所有送中或离线的一票否决端口。"""
    if not CONFIDENCE_FILE.exists():
        return []
    try:
        conf = json.loads(CONFIDENCE_FILE.read_text(encoding="utf-8")).get("ports", {})
    except Exception:
        return []

    active_scope = get_protected_bound_ports() if scope == "bound" else None

    results = []
    for port_str, rec in conf.items():
        try:
            port = int(port_str)
        except ValueError:
            continue

        # 核心保护：若限定为 bound 范围，非在用保护端口绝不触发全量热替换，避免误伤历史空闲端口！
        if active_scope is not None and port not in active_scope:
            continue

        # 检查是否触发自愈条件：被一票否决、离线或最近一次实测为 China
        last_probe = rec.get("lastProbe") or {}
        g_country = str(last_probe.get("googleCountry") or "").lower()
        veto_reason = rec.get("vetoReason") or ""
        last_drift = ((rec.get("driftEvents") or [{}])[-1]).get("kind") or ""

        # 防震荡冷却门禁：若距离上次换绑不足 3600 秒 (1小时)，跳过，坚决防止 A <-> B 频繁来回横跳！
        last_healed = float(rec.get("lastHealedTime") or 0.0)
        if time.time() - last_healed < 3600.0:
            continue

        needs_heal = False
        reason = ""
        if is_blocked_google_country(g_country) or veto_reason == "sent_to_china":
            needs_heal = True
            reason = "sent_to_china"
        elif rec.get("offline") or veto_reason == "offline":
            needs_heal = True
            reason = "node_offline"
        elif last_drift in ("cross_continent", "cross_country_same_region"):
            # 跨洲/同大区跨国漂移同样纳入自愈候选（原有「送中/离线必换」语义不变）。
            # select_candidate_node 内的跨大区拒绝保护依然生效：选不到同区候选即返回 no_candidate。
            needs_heal = True
            reason = f"drift_{last_drift}"

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
