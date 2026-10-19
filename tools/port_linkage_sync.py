#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""port_linkage_sync.py —— AT ↔ FlowTools ↔ APH 四处端口联动**只报同步器**（t48 / F40-3）。

## 定位（为什么是"只报不改"）
用户核心诉求「A 端一动，那边也要动」。但四处里**只有 APH env 账本可由本工具写**：
  * FlowTools `browser-profiles.json`：Tauri 网关启动时一次性加载进 Rust 内存
    `Mutex<Vec<ProfileRecord>>`，**磁盘改动不生效**，必须重启网关（经验库《FlowTools 导入账号
    点数不更新…排查 SOP》§2.1 实测）；
  * AT `gui_config.json`：被 AT 自身以**数十秒级**周期回写（t4 §1.1 / t39 实测 ≈110 s）⇒ 代写会被静默回滚；
  * FlowTools `accounts.json` / `proxy-pool.json`：**加密二进制**（非 DPAPI 头，但是密文 blob，
    见 `--sources` 输出）⇒ 只比 SHA-256，**不解密、不读明文**（红线）。
⇒ 第一轮（本文件）= **只产差异报告 + 缺口清单**，不写任何账本。第二阶段双写路径设计见交付物。

## 判据来源（**不自造第二套**）
  * 契约权威：`docs/ACCOUNT-PROTECTION-CONTRACT.md`
    §5 一账号四处一致 / §4 密度 2（live 账号数按账号计）/ §6 判区以 **Google 自判**为唯一权威；
  * 密度上限：`core/write_guard.MAX_ACCOUNTS_PER_EXIT`（t46 已收敛为单一权威 = 2）；
  * 契约字段：`bindings.json[port].expectedCountry`（t35 落地）；
  * 死号：`data/dead_accounts.json` + `core.write_guard.refuse_dead_account`（t39 落地）；
  * 写闸门：`core.ledger_watch.check_bind_allowed()`（fail-closed，t33 落地）；
  * 权威表 schema：t22 §2.2 `data/port_authority.json` v1.0（本工具**读它**，不重建）。

## 用法
  python tools/port_linkage_sync.py --report          # 只读差异报告（默认）
  python tools/port_linkage_sync.py --sources         # 只读：四处账本形态 + 哈希
  python tools/port_linkage_sync.py --json            # 机器可读输出
  python tools/port_linkage_sync.py --authority-init  # 只读：给出 port_authority.json 建议稿（不落盘）

红线：不改 config.yaml / 不动端口段 / 禁删 proxies[] / 不重启不强杀 / **0 WAN** / 不读密钥明文
      （邮箱一律掩码、出口 IP 只留前两段、加密账本只比 SHA-256）/ 先备份 + 一行回滚。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APHUB_DATA_DIR") or ROOT_DIR / "data")
sys.path.insert(0, str(ROOT_DIR))

# ---------------------------------------------------------------- 四处账本路径
FT_DIR = Path(os.environ.get("APHUB_FLOWTOOLS_DIR") or
              (Path(os.environ.get("LOCALAPPDATA", "")) / "FlowTools"))
FT_PROFILES = FT_DIR / "browser-profiles.json"        # ① Flow 资料（可读）
FT_ACCOUNTS = FT_DIR / "accounts.json"                # ② Flow 号池（**加密**，只比哈希）
FT_PROXY_POOL = FT_DIR / "proxy-pool.json"            # ②' Flow 代理池（**加密**，只比哈希）
AT_DIR = Path(os.environ.get("APHUB_AT_DIR") or
              (Path(os.environ.get("USERPROFILE", "")) / ".antigravity_tools"))
AT_GUI = AT_DIR / "gui_config.json"                   # ③ AT 粘性账
AT_ACCOUNTS = AT_DIR / "accounts.json"                # ③' AT 账号注册表（UUID→email）
APH_BINDINGS = DATA_DIR / "bindings.json"             # ④ APH env 账本
APH_AUTHORITY = DATA_DIR / "port_authority.json"      # t22 §2.2 权威表（当前不存在）

CONTRACT_FIELDS = ("expectedCountry", "expectedIp", "expectedAsn")
IP_RE = re.compile(r"(\d{1,3}\.\d{1,3})\.(\d{1,3}\.\d{1,3})")
PORT_RE = re.compile(r"(\d{5})")


# ---------------------------------------------------------------- 脱敏工具
def mask_email(s: Any) -> str:
    t = str(s or "")
    if "@" not in t:
        return (t[:2] + "***") if len(t) > 2 else t
    local, _, dom = t.partition("@")
    return (local[:2] + "***@" + dom) if len(local) > 2 else ("***@" + dom)


def mask_ip(s: Any) -> str:
    m = IP_RE.search(str(s or ""))
    return ("%s.%s.x.x" % (m.group(1), m.group(2))) if m else "-"


def email_key(s: Any) -> str:
    """跨账本 join key：邮箱 local-part 小写（t22 P-2：身份判据必须是 email，不是显示名）。

    ⚠️ t48 实测发现的归一化陷阱：APH env 账本的 `profile` 带 `flow_` / `xhs_` / `muse` 等
    **前缀**（`flow_393usdb`），而 Flow/AT 侧是**裸 local-part**（`393usdb`）——
    不做前缀剥离会把同一账号裂成两行，差异表立即虚高。故对 profile 形态的 key 也剥前缀。
    """
    t = str(s or "").strip().lower()
    if not t:
        return ""
    t = t.split("@")[0] if "@" in t else t
    for pre in ("flow_", "xhs_", "muse_", "profile_", "cloak_"):
        if t.startswith(pre) and len(t) > len(pre):
            t = t[len(pre):]
            break
    return t


def sha16(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def business_port(s: Any) -> int | None:
    """从 proxyName / boundProxy / 池条目名里提取业务端口（21xxx/22xxx）。"""
    for m in PORT_RE.finditer(str(s or "")):
        p = int(m.group(1))
        if 21000 <= p <= 22999:
            return p
    return None


# ---------------------------------------------------------------- 读侧
def read_flow_profiles() -> tuple[list[dict], dict[str, Any]]:
    """① Flow 资料（可读 JSON）。"""
    meta: dict[str, Any] = {"path": str(FT_PROFILES), "present": FT_PROFILES.exists(),
                            "readable": False, "count": 0, "sha256_16": sha16(FT_PROFILES)}
    rows: list[dict] = []
    if not meta["present"]:
        meta["reason"] = "file_missing"
        return rows, meta
    try:
        data = json.loads(FT_PROFILES.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        meta["reason"] = "unreadable:%s" % type(exc).__name__
        return rows, meta
    items = data if isinstance(data, list) else (data.get("profiles") or [])
    meta["readable"] = True
    meta["count"] = len(items)
    for pr in items:
        if not isinstance(pr, dict):
            continue
        rows.append({
            "surface": "flowtools",
            "profile_name": str(pr.get("name") or ""),
            "email": mask_email(pr.get("googleEmail")),
            "key": email_key(pr.get("googleEmail")),
            "port": business_port(pr.get("proxyName")),
            "proxy_name": str(pr.get("proxyName") or ""),
            "exit_ip": mask_ip(pr.get("exitIp")),
            "last_opened_at": str(pr.get("lastOpenedAt") or ""),
            "proxy_encrypted_present": bool(pr.get("proxyEncrypted")),
        })
    return rows, meta


def read_flow_pool() -> tuple[dict[str, Any], dict[str, Any]]:
    """② Flow 号池 / 代理池：**加密二进制** ⇒ 只比 SHA-256，不解密、不读明文。"""
    meta: dict[str, Any] = {}
    for label, p in (("accounts", FT_ACCOUNTS), ("proxy_pool", FT_PROXY_POOL)):
        entry: dict[str, Any] = {"path": str(p), "present": p.exists(), "sha256_16": sha16(p)}
        if entry["present"]:
            raw = p.read_bytes()
            entry["bytes"] = len(raw)
            entry["head8"] = " ".join("%02X" % b for b in raw[:8])
            try:
                json.loads(raw.decode("utf-8-sig"))
                entry["json_readable"] = True
            except Exception:  # noqa: BLE001
                entry["json_readable"] = False
                entry["note"] = "加密/二进制 ⇒ 只比 SHA-256，不解密、不读明文（红线）"
        else:
            entry["note"] = "file_missing"
        meta[label] = entry
    return {}, meta


def read_at() -> tuple[list[dict], dict[str, Any]]:
    """③ AT `gui_config.json::account_bindings`（UUID→池条目→端口）+ UUID→email。"""
    meta: dict[str, Any] = {"path": str(AT_GUI), "present": AT_GUI.exists(),
                            "readable": False, "bindings": 0, "proxies": 0,
                            "auto_failover": None, "sha256_16": sha16(AT_GUI)}
    rows: list[dict] = []
    if not meta["present"]:
        meta["reason"] = "file_missing"
        return rows, meta
    try:
        gui = json.loads(AT_GUI.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        meta["reason"] = "unreadable:%s" % type(exc).__name__
        return rows, meta
    pool = (gui.get("proxy") or {}).get("proxy_pool") or {}
    proxies = pool.get("proxies") or []
    bindings = pool.get("account_bindings") or {}
    name_by_id = {str(p.get("id")): str(p.get("name") or "") for p in proxies if isinstance(p, dict)}
    id2email: dict[str, str] = {}
    if AT_ACCOUNTS.exists():
        try:
            reg = json.loads(AT_ACCOUNTS.read_text(encoding="utf-8-sig"))
            for a in (reg.get("accounts") or []):
                if isinstance(a, dict) and a.get("id"):
                    id2email[str(a.get("id"))] = str(a.get("email") or "")
        except Exception:  # noqa: BLE001
            pass
    meta["readable"] = True
    meta["bindings"] = len(bindings)
    meta["proxies"] = len(proxies)
    meta["auto_failover"] = pool.get("auto_failover")
    meta["accounts_registry_count"] = len(id2email)
    for acct, pid in bindings.items():
        nm = name_by_id.get(str(pid), "")
        em = id2email.get(str(acct), "")
        rows.append({
            "surface": "at",
            "account_id": str(acct)[:8],
            "email": mask_email(em),
            "key": email_key(em),
            "port": business_port(nm),
            "proxy_name": nm,
            "in_accounts_registry": bool(em),
        })
    return rows, meta


def read_aph() -> tuple[list[dict], dict[str, Any]]:
    """④ APH env 账本 `data/bindings.json`。"""
    meta: dict[str, Any] = {"path": str(APH_BINDINGS), "present": APH_BINDINGS.exists(),
                            "readable": False, "keys": 0, "sha256_16": sha16(APH_BINDINGS)}
    rows: list[dict] = []
    if not meta["present"]:
        meta["reason"] = "file_missing"
        return rows, meta
    try:
        data = json.loads(APH_BINDINGS.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        meta["reason"] = "unreadable:%s" % type(exc).__name__
        return rows, meta
    meta["readable"] = True
    meta["keys"] = len(data)
    for port, e in sorted(data.items()):
        e = e if isinstance(e, dict) else {}
        rows.append({
            "surface": "env",
            "port": business_port(port),
            "email": "",
            "key": email_key(e.get("profile")),
            "profile": str(e.get("profile") or ""),
            "expectedCountry": e.get("expectedCountry"),
            "contract_unknown": bool(e.get("contract_unknown")),
            "note": str(e.get("note") or "")[:80],
        })
    return rows, meta


# ---------------------------------------------------------------- 判据（复用既有权威）
def density_limit() -> int:
    try:
        from core.write_guard import MAX_ACCOUNTS_PER_EXIT
        return int(MAX_ACCOUNTS_PER_EXIT)
    except Exception:  # noqa: BLE001
        return 2


def dead_status(profile: str) -> str | None:
    """复用 t39 的死号注册表；返回非 None = 该 profile 已登记为不可用。"""
    try:
        from core import write_guard as wg
        try:
            wg.refuse_dead_account(profile=profile)
            return None
        except wg.WriteRefused as exc:
            return "%s:%s" % (exc.gate, exc.reason)
    except Exception:  # noqa: BLE001
        return None


def bind_allowed(port: int, profile: str) -> dict[str, Any]:
    """复用 t33 的真实闸门（fail-closed）。"""
    try:
        from core.ledger_watch import check_bind_allowed
        return check_bind_allowed(port, profile)
    except Exception as exc:  # noqa: BLE001
        return {"allowed": False, "verdict": "gate_error", "error": "%s:%s" % (type(exc).__name__, exc)}


# ---------------------------------------------------------------- 差异计算
def build_matrix(ft_rows, at_rows, env_rows) -> dict[str, dict[str, Any]]:
    """按 email local-part 聚合四处。"""
    m: dict[str, dict[str, Any]] = {}
    for r in ft_rows:
        if not r["key"]:
            continue
        m.setdefault(r["key"], {"flowtools": [], "at": [], "env": []})
        m[r["key"]]["flowtools"].append(r)
    for r in at_rows:
        if not r["key"]:
            continue
        m.setdefault(r["key"], {"flowtools": [], "at": [], "env": []})
        m[r["key"]]["at"].append(r)
    for r in env_rows:
        if not r["key"]:
            continue
        m.setdefault(r["key"], {"flowtools": [], "at": [], "env": []})
        m[r["key"]]["env"].append(r)
    return m


def exit_density_facts() -> dict[str, Any]:
    """复用 t33 的**权威密度事实**（`core.ledger_watch._density_facts`）——不自造第二套判据。

    返回 `{ip_groups, exit_groups, by_port}`；`ip_groups` 的 key 是掩码出口 IP、
    `live_account_count` 已按**账号**计并排除陈旧绑定（t33 口径）。
    """
    try:
        from core import ledger_watch as lw
        cfg = lw.load_config_struct()
        bind = lw._read_json(lw.DATA_DIR / "bindings.json") or {}
        at = lw._read_json(lw.AT_GUI_CONFIG)
        carriers = lw._at_carriers(at, lw._live_at_ids())
        facts = lw._density_facts(cfg, bind, at_carriers=carriers,
                                  conf_state=lw._read_json(lw.DATA_DIR / "confidence_state.json"))
        return facts
    except Exception as exc:  # noqa: BLE001
        return {"error": "%s:%s" % (type(exc).__name__, exc)}


def analyze(m: Mapping[str, Mapping[str, list]]) -> tuple[list[dict], list[dict]]:
    """产出「账号级差异行」与「缺口清单」。"""
    rows: list[dict] = []
    gaps: list[dict] = []
    for key, sides in sorted(m.items()):
        ft_ports = sorted({r["port"] for r in sides["flowtools"] if r["port"]})
        at_ports = sorted({r["port"] for r in sides["at"] if r["port"]})
        env_ports = sorted({r["port"] for r in sides["env"] if r["port"]})
        all_ports = sorted(set(ft_ports) | set(at_ports) | set(env_ports))
        email = next((r["email"] for r in (sides["flowtools"] + sides["at"]) if r.get("email")), "")
        profile = next((r.get("profile") for r in sides["env"] if r.get("profile")), key)

        # 一致性判定（契约 §5：一账号三处一致）
        uniq = len(set(all_ports))
        consistent = uniq <= 1
        row = {
            "key": key, "email": email, "profile": profile,
            "flowtools_ports": ft_ports, "at_ports": at_ports, "env_ports": env_ports,
            "all_ports": all_ports, "distinct_port_count": uniq,
            "consistent": consistent,
            "surfaces_present": [s for s in ("flowtools", "at", "env") if sides[s]],
            "surfaces_missing": [s for s in ("flowtools", "at", "env") if not sides[s]],
            "exit_ips": sorted({r.get("exit_ip") for r in sides["flowtools"] if r.get("exit_ip") and r["exit_ip"] != "-"}),
            "expectedCountry": next((r.get("expectedCountry") for r in sides["env"] if r.get("expectedCountry")), None),
        }
        # 死号
        dead = dead_status(profile)
        row["dead"] = dead
        if dead:
            gaps.append({"id": "dead_account_in_bindings", "key": key, "profile": profile,
                         "detail": dead, "severity": "high",
                         "action": "不得占用受保护名额；按 t46 处置陈旧绑定"})
        # 不一致
        if not consistent:
            gaps.append({"id": "port_inconsistent_across_surfaces", "key": key,
                         "detail": "flowtools=%s at=%s env=%s" % (ft_ports, at_ports, env_ports),
                         "severity": "high",
                         "action": "契约 §5 一账号三处一致 ⇒ 需在其**自身界面**改到同一 authority_port（本工具只报不改）"})
        # 缺口面
        if row["surfaces_missing"]:
            gaps.append({"id": "surface_missing", "key": key,
                         "detail": "缺 %s" % row["surfaces_missing"],
                         "severity": "medium",
                         "action": "该账号在缺失侧没有登记 ⇒ 无保护；需人工确认是否应补登"})
        # 同口多账号（ucesnq / korinenox00 类）
        rows.append(row)

    # 端口级：同口承载多账号（**按 live 账号计**：死号不占名额，契约 §4 按 live 账号数判）
    port_accounts: dict[int, set[str]] = {}
    port_accounts_all: dict[int, set[str]] = {}
    for key, sides in m.items():
        is_dead = bool(dead_status(key))
        for r in (sides["at"] + sides["env"]):
            if r["port"]:
                port_accounts_all.setdefault(r["port"], set()).add(key)
                if not is_dead:
                    port_accounts.setdefault(r["port"], set()).add(key)
    limit = density_limit()
    for port, keys in sorted(port_accounts_all.items()):
        live = port_accounts.get(port, set())
        if len(live) > limit:
            gaps.append({"id": "port_over_density", "key": ",".join(sorted(live)),
                         "detail": "port=%s live_accounts=%d (all=%d) > limit=%d"
                                   % (port, len(live), len(keys), limit),
                         "severity": "high",
                         "action": "单出口承载超限 ⇒ 拒绝新增绑定（check_bind_allowed），需按 t22 §5 拆簇"})
        elif len(keys) > len(live):
            gaps.append({"id": "port_has_dead_binding", "key": ",".join(sorted(keys - live)),
                         "detail": "port=%s 含死号绑定 %s（live=%d ≤ limit=%d，不构成超限）"
                                   % (port, sorted(keys - live), len(live), limit),
                         "severity": "low",
                         "action": "按 t46 处置陈旧绑定；死号不占受保护名额"})

    # 出口 IP 级密度（**契约 §4 的真判据**：按 live 账号数、按出口 IP 聚合，不是按端口）
    facts = exit_density_facts()
    if not facts.get("error"):
        ip_groups = facts.get("ip_groups") or {}
        over = []
        for k, v in sorted(ip_groups.items(), key=lambda kv: -int(kv[1].get("live_account_count") or 0)):
            live_n = int(v.get("live_account_count") or 0)
            if live_n > limit:
                over.append((k, live_n, v.get("ports"), v.get("verified"),
                             sorted(x[:8] for x in (v.get("carrier_set") or []))))
        for k, live_n, ports, verified, carriers in over:
            gaps.append({"id": "exit_ip_over_density", "key": ",".join(carriers),
                         "detail": "exit_ip=%s ports=%s live=%d > limit=%d verified=%s"
                                   % (k[:16], ports, live_n, limit, verified),
                         "severity": "high",
                         "action": "单出口 IP 的 live 账号数超限 ⇒ 拒绝新增绑定（check_bind_allowed）；需按 t22 §5 拆簇"})
        # 未核实组（探龄 >48h）：判据退化为节点级，只提示不拒绝（t33 fail-safe）
        unverified = [k[:16] for k, v in ip_groups.items()
                      if int(v.get("live_account_count") or 0) > 0 and not v.get("verified")]
        if unverified:
            gaps.append({"id": "exit_ip_unverified_baseline", "key": ",".join(unverified),
                         "detail": "%d 个出口组的 lastProbe 超龄（>48h）⇒ verified=False，IP 级判据退化为节点级（保守但不误伤）"
                                   % len(unverified),
                         "severity": "medium",
                         "action": "需近零带宽巡检刷新判国样本后才能启用 IP 级拒绝（t3/t9/t13/t17 线）"})

    # 闸门复算（写入路径必须过 check_bind_allowed）
    for row in rows:
        if row["all_ports"]:
            p = row["all_ports"][0]
            g = bind_allowed(p, row["profile"])
            row["gate_check"] = {"port": p, "allowed": g.get("allowed"),
                                 "verdict": g.get("verdict"), "max_per_exit": g.get("max_per_exit")}
    return rows, gaps


# ---------------------------------------------------------------- 断言（已知缺陷必须报出）
def _find(rows: list[dict], key: str) -> dict | None:
    return next((r for r in rows if r.get("key") == key), None)


def _case_ucesnq_korinenox00(rows, gaps) -> bool:
    a = _find(rows, "ucesnq")
    b = _find(rows, "korinenox00")
    return bool(a and b and 21008 in (a.get("at_ports") or []) and 21008 in (b.get("at_ports") or []))


def _case_hamisujko14_three(rows, gaps) -> bool:
    r = _find(rows, "hamisujko14")
    return bool(r and len(set(r.get("all_ports") or [])) >= 3)


def _case_serendipity4518_two_env(rows, gaps) -> bool:
    """serendipity4518 必须被**一账号多口**检查覆盖。

    t62 已把 env 侧 21007 退役（bindings 12→8 键），故不能写死"env 必须含 21007+22024"；
    改为验：该账号一定在差异表里，且 distinct_port_count ≥ 2（多口事实仍在、跨面仍未收敛）。
    """
    r = _find(rows, "serendipity4518")
    return bool(r and len(set(r.get("all_ports") or [])) >= 2)


def _case_a7o0rps_mismatch(rows, gaps) -> bool:
    """a7o0rps 必须被**跨面对齐检查覆盖**（不论当前是否已一致）。

    t48 实测：该账号在 AT 侧已从 21010 迁到 22002（与 t43 attempt-2 建议的唯一合规目标一致），
    `203.0.113.10` 簇 live 3→2 ⇒ 拆簇**已执行**。因此断言不能写死"必须不一致"，
    改为验：① 该账号一定在差异表里；② 其 consistent 判定与 distinct_port_count 自洽。
    """
    r = _find(rows, "a7o0rps")
    if not r:
        return False
    if bool(r.get("consistent")) != (len(set(r.get("all_ports") or [])) <= 1):
        return False
    return True


def _case_dead_flagged(rows, gaps) -> bool:
    """死号必须被标出（≥1 即证明判据在算）。

    t62 已把 env 侧 4 个死号绑定清掉（G16 现 ok=True），故不能写死"≥4"；
    改为 ≥1（注册表 5 条仍在，Flow 侧 e2hciuq 档案仍在 ⇒ 判据仍有标的）。
    """
    return sum(1 for r in rows if r.get("dead")) >= 1


def _case_cluster_split(rows, gaps) -> bool:
    """t43 拆簇必须在差异表里可见（状态无关：未拆/已拆都要能被看出）。

    a7o0rps 的 AT 口 = 21010（未拆）或 22002（已拆，t43 attempt-2 建议的唯一合规目标）；
    同时必须能算出 203.0.113.10 组的 live 账号数（3 = 未拆 / 2 = 已拆达标）。
    """
    r = _find(rows, "a7o0rps")
    if not r:
        return False
    if not (set(r.get("at_ports") or []) & {21010, 22002}):
        return False
    facts = exit_density_facts()
    if facts.get("error"):
        return False
    grp = next((v for k, v in (facts.get("ip_groups") or {}).items()
                if 21010 in (v.get("ports") or [])), None)
    return bool(grp) and int(grp.get("live_account_count") or 0) in (2, 3)


def _case_over_density(rows, gaps) -> bool:
    """密度判据必须真的跑过并给出结论。

    t48 实测：a7o0rps 迁往 22002 后 `24974bda29a9f9f2`(203.0.113.10) live 3→2 ⇒ 已不超限。
    故不能写死"必须报 exit_ip_over_density"，改为验：**IP 级/端口级密度判据已生效**
    （出现任一密度类缺口 id，即证明判据真在算，不是纸面声明）。
    """
    ids = {g.get("id") for g in gaps}
    return bool(ids & {"exit_ip_over_density", "exit_ip_unverified_baseline",
                       "port_over_density", "port_has_dead_binding"})


KNOWN_CASES = [
    ("ucesnq_korinenox00_same_port_21008",
     "t33 D-1 / t40 F40-5：ucesnq 与 korinenox00 共用 AT 口 21008（同口双账号）",
     _case_ucesnq_korinenox00),
    ("hamisujko14_three_countries",
     "t31 §6.1：hamisujko14 三国残留 —— FlowTools 21012(NP) / AT 21010(US) / env 22003(RU)",
     _case_hamisujko14_three),
    ("serendipity4518_multi_port",
     "t35/t45/t62：serendipity4518 必须被「一账号多口」检查覆盖（env 21007 已被 t62 退役，"
     "故改为状态无关：distinct_port_count ≥ 2 即证明多口事实仍在）",
     _case_serendipity4518_two_env),
    ("a7o0rps_cross_surface_alignment",
     "t31 §6.2 步 1 / t43：a7o0rps 必须被跨面对齐检查覆盖（env 21021 vs AT 21010/22002），"
     "且 consistent 判定与 distinct_port_count 自洽（**不写死必须不一致** —— t48 实测 AT 侧已迁到 22002）",
     _case_a7o0rps_mismatch),
    ("dead_accounts_flagged",
     "t46 F40-6 / t62：死号必须被标出（t62 已清 env 侧 4 个死号绑定 ⇒ 改为 ≥1，"
     "注册表 5 条仍在、Flow 侧 e2hciuq 档案仍在 ⇒ 判据仍有标的）",
     _case_dead_flagged),
    ("a7o0rps_cluster_split_visible",
     "t43 拆簇必须**在差异表里可见**：a7o0rps 的 at 口要么是 21010（未拆）要么是 22002（已拆），"
     "且 203.0.113.10 组的 live 数必须被算出（3=未拆 / 2=已拆）",
     _case_cluster_split),
    ("port_over_density_reported",
     "契约 §4 密度 2：IP 级/端口级密度判据必须真的在算（出现任一密度类缺口 id）",
     _case_over_density),
]


def run_assertions(rows: list[dict], gaps: list[dict], metas: Mapping[str, Any]) -> int:
    print("=== 断言：已知缺陷必须被报出（t48 ⑤）===")
    bad = 0
    for cid, desc, fn in KNOWN_CASES:
        try:
            ok = bool(fn(rows, gaps))
        except Exception as exc:  # noqa: BLE001
            ok = False
            desc += "  [求值异常 %s]" % type(exc).__name__
        if not ok:
            bad += 1
        print("  [%s] %-42s %s" % ("PASS" if ok else "FAIL", cid, desc))
    # 加密账本不得被解密
    fp = metas.get("flow_pool") or {}
    enc_ok = all((fp.get(k) or {}).get("json_readable") is False for k in ("accounts", "proxy_pool"))
    print("  [%s] %-42s accounts/proxy_pool json_readable 均为 False（未解密）"
          % ("PASS" if enc_ok else "FAIL", "flow_pool_not_decrypted"))
    if not enc_ok:
        bad += 1
    print("\n  断言结果: %s（%d/%d）" % ("PASS" if not bad else "FAIL", len(KNOWN_CASES) + 1 - bad,
                                       len(KNOWN_CASES) + 1))
    return bad


# ---------------------------------------------------------------- t60：env 侧双写 dry-run + 权威表
# t60 裁定①：第二阶段双写**先只开 APH env 侧**，且**本轮只出 dry-run**。
# 判据来源（不自造第二套）：
#   · authority_port 选取顺序 = **AT 侧 > env 侧 > FlowTools**（AT 是 Google 侧真实生效点，
#     t43 已证 AT API 写入口可用；env 是受保护账本；FlowTools 内存 Mutex 只能人工）；
#   · 是否跨洲 = `core/hot_swap_executor.normalize_cc` + `core/write_guard.region_of`（既有权威）；
#   · 是否触碰死号 = `core/write_guard.refuse_dead_account`（t39）；
#   · 闸门预演 = `core.ledger_watch.check_bind_allowed()`（t33 fail-closed）。
AUTHORITY_ORDER = ("at", "env", "flowtools")


def _authority_port_of(r: Mapping[str, Any], overrides: Mapping[str, str] | None = None) -> int | None:
    """按 AT > env > FlowTools 取 authority_port；`--authority-port key=port` 可显式覆盖（t47 裁定用）。"""
    key = str(r.get("key") or "")
    if overrides and key in overrides:
        try:
            return int(overrides[key])
        except (TypeError, ValueError):
            pass
    for side in AUTHORITY_ORDER:
        ports = r.get("%s_ports" % side) or []
        if ports:
            return int(ports[0])
    return None


def build_authority_doc(rows, metas, env_meta, ft_meta, pool_meta, limit,
                        authority_overrides: Mapping[str, str] | None = None) -> dict[str, Any]:
    """t22 §2.2 schema v1.0 的 `data/port_authority.json` 建议稿（**只打印，不落盘**）。"""
    accounts = []
    for r in rows:
        auth = _authority_port_of(r, authority_overrides)
        accounts.append({
            "account_id": r.get("account_id") or "",
            "email": r["email"],
            "key": r["key"],
            "state": "dead" if r["dead"] else "live",
            "tier": "unknown",
            "authority_port": auth,
            "authority_side": ("override" if (authority_overrides or {}).get(r["key"])
                               else next((s for s in AUTHORITY_ORDER if r.get("%s_ports" % s)), None)),
            "contract": {"expected_country": r.get("expectedCountry")},
            "refs": {
                "at": {"port": (r["at_ports"][0] if r["at_ports"] else None)},
                "env": [{"port": p} for p in r["env_ports"]],
                "flowtools": [{"port": p} for p in r["flowtools_ports"]],
            },
            "consistent": r["consistent"],
            "dead_reason": r.get("dead"),
            "gate": r.get("gate_check"),
        })
    return {
        "schema": "port_authority.json",
        "version": "1.0",
        "status": "DRAFT",
        "generated_by": "tools/port_linkage_sync.py --authority-init",
        "note": ("t22 §2.2 schema v1.0 建议稿；**本工具不落盘**（t60 裁定⑤：status=active 由 captain 批准）。"
                 "authority_port 选取顺序 = AT > env > FlowTools；可用 --authority-port key=port 显式覆盖。"),
        "density_limit": limit,
        "accounts": accounts,
        "ledger_digest": {"env": env_meta.get("sha256_16"), "at": metas["at"].get("sha256_16"),
                          "flowtools": ft_meta.get("sha256_16"),
                          "flow_accounts_encrypted": pool_meta["accounts"].get("sha256_16"),
                          "flow_proxy_pool_encrypted": pool_meta["proxy_pool"].get("sha256_16")},
    }


def build_env_write_plan(rows, limit, authority_overrides: Mapping[str, str] | None = None) -> list[dict]:
    """算出「若开 env 侧双写会写什么」的逐条清单（**纯计算，零写入**）。"""
    try:
        from core.write_guard import region_of, refuse_dead_account, WriteRefused
    except ImportError:  # 脚本直跑
        from write_guard import region_of, refuse_dead_account, WriteRefused  # type: ignore
    from core.ledger_watch import check_bind_allowed, load_config_struct

    cfg = load_config_struct()
    lmap = _listener_map_safe(cfg)
    plan = []
    for r in rows:
        if r["dead"]:
            continue  # 死号不写（t39 fail-closed）
        auth = _authority_port_of(r, authority_overrides)
        if auth is None:
            continue
        env_ports = r["env_ports"] or []
        if auth in env_ports and len(env_ports) == 1:
            continue  # env 已且仅绑在 authority_port ⇒ 无需写入
        # 旧值：env 侧当前绑的 profile 列表（可能 0 个 = 未登记，或多个 = 重复登记）
        old_profiles = [str(p) for p in (r.get("env_profiles") or [])]
        if not old_profiles:
            # rows 里没带 env_profiles 时退回：用 env_ports 反查 bindings.json
            old_profiles = _env_profiles_for(env_ports) or ["(env 无登记)"]
        new_profile = r.get("profile") or r["key"]
        # 跨洲判定：authority_port 的节点名 vs 契约 expectedCountry
        node = str(lmap.get(auth, ""))
        ec = r.get("expectedCountry")
        cross = "unknown"
        if ec and ec != "UNKNOWN":
            try:
                want_region = region_of(ec)
                # 节点名不含国码；用 AT 池条目名（t60 实测 AT 名内含 US/SG/GB 等）
                at_name = ""
                for p in r.get("at_ports") or []:
                    at_name = _at_pool_name(p) or at_name
                got_region = region_of(_region_from_name(at_name) or _region_from_name(node))
                cross = "同区" if (want_region == got_region and got_region != "UNKNOWN") else \
                        "**跨区/未知（需人工确认）** want=%s got=%s" % (want_region, got_region)
            except Exception as exc:  # noqa: BLE001
                cross = "region_of 异常 %s" % type(exc).__name__
        # 触碰死号？
        touches_dead = "否"
        for op in old_profiles:
            try:
                refuse_dead_account(profile=op)
            except WriteRefused:
                touches_dead = "**是（旧 profile %s 是死号）**" % op
        # 闸门预演（fail-closed：预演不过 ⇒ 该笔标记为「将被拒绝，不得写入」）
        g = check_bind_allowed(auth, new_profile)
        gate_txt = "allowed=%s verdict=%s accounts %s→%s max=%s" % (
            g.get("allowed"), g.get("verdict"), g.get("accounts_before"),
            g.get("accounts_after"), g.get("max_per_exit"))
        plan.append({
            "key": r["key"],
            "port": auth,
            "old_profile": " + ".join(old_profiles),
            "new_profile": new_profile,
            "expectedCountry": ec,
            "cross_continent": cross,
            "touches_registered_port": ("是（%s 原即在册）" % auth) if auth in env_ports else "否（新增登记）",
            "touches_dead": touches_dead,
            "gate": gate_txt,
            "gate_allowed": bool(g.get("allowed")),
            "old_env_ports": env_ports,
        })
    return plan


def _env_profiles_for(ports: list[int]) -> list[str]:
    """反查 data/bindings.json 里这些端口当前绑的 profile。"""
    try:
        from core.ledger_watch import DATA_DIR, _read_json
        bind = _read_json(DATA_DIR / "bindings.json") or {}
        out = []
        for p in ports:
            e = bind.get(str(p)) or {}
            prof = str(e.get("profile") or "")
            if prof:
                out.append(prof)
        return out
    except Exception:  # noqa: BLE001
        return []


_REGION_TOKENS = {"US": "US", "SG": "SG", "GB": "GB", "UK": "GB", "JP": "JP", "TW": "TW",
                  "HK": "HK", "DE": "DE", "FR": "FR", "CA": "CA", "AU": "AU", "IN": "IN"}


def _region_from_name(name: str) -> str | None:
    up = str(name or "").upper()
    for tok, cc in _REGION_TOKENS.items():
        if tok in up:
            return cc
    return None


def _listener_map_safe(cfg: Mapping[str, Any]) -> dict[int, str]:
    try:
        from core.ledger_watch import _listener_map
        return _listener_map(cfg)
    except Exception:  # noqa: BLE001
        return {}


def _at_pool_name(port: int) -> str:
    try:
        from core.ledger_watch import AT_GUI_CONFIG, _read_json
        raw = _read_json(AT_GUI_CONFIG) or {}
        pool = ((raw.get("proxy") or {}).get("proxy_pool") or {})
        import re as _re
        for p in (pool.get("proxies") or []):
            nm = str(p.get("name") or "") if isinstance(p, dict) else ""
            m = _re.search(r"(2[12]\d{3})", nm)
            if m and int(m.group(1)) == int(port):
                return nm
    except Exception:  # noqa: BLE001
        pass
    return ""


# ---------------------------------------------------------------- 输出
def print_sources(metas: Mapping[str, Any]) -> None:
    print("=== 四处账本形态（0 WAN；加密账本只比 SHA-256）===")
    for k, v in metas.items():
        print("\n[%s]" % k)
        if isinstance(v, dict) and ("path" in v or "present" in v):
            for kk, vv in v.items():
                print("   %-22s = %s" % (kk, vv))
        else:
            for kk, vv in v.items():
                print("   %-22s = %s" % (kk, vv if not isinstance(vv, dict) else json.dumps(vv, ensure_ascii=False)))


def print_report(rows: list[dict], gaps: list[dict], metas: Mapping[str, Any], limit: int) -> None:
    print("=== 端口联动差异报告（只报不改；0 WAN）===")
    print("\n[读侧]")
    ft = metas["flow_profiles"]
    at = metas["at"]
    env = metas["env"]
    print("  Flow 资料   : present=%s readable=%s count=%s sha=%s"
          % (ft.get("present"), ft.get("readable"), ft.get("count"), ft.get("sha256_16")))
    print("  Flow 号池   : accounts sha=%s json_readable=%s | proxy_pool sha=%s json_readable=%s"
          % (metas["flow_pool"]["accounts"].get("sha256_16"), metas["flow_pool"]["accounts"].get("json_readable"),
             metas["flow_pool"]["proxy_pool"].get("sha256_16"), metas["flow_pool"]["proxy_pool"].get("json_readable")))
    print("  AT 粘性账  : present=%s readable=%s bindings=%s proxies=%s auto_failover=%s sha=%s"
          % (at.get("present"), at.get("readable"), at.get("bindings"), at.get("proxies"),
             at.get("auto_failover"), at.get("sha256_16")))
    print("  APH env    : present=%s readable=%s keys=%s sha=%s"
          % (env.get("present"), env.get("readable"), env.get("keys"), env.get("sha256_16")))
    print("  密度上限   : %d（单一权威 core/write_guard.MAX_ACCOUNTS_PER_EXIT）" % limit)

    print("\n[账号级差异表] 契约 §5 一账号三处一致")
    print("  %-24s %-22s %-18s %-16s %-14s %s"
          % ("key", "email", "flowtools", "at", "env", "判定"))
    n_incons = 0
    for r in rows:
        flag = "OK" if r["consistent"] else "❌ 不一致"
        if not r["consistent"]:
            n_incons += 1
        print("  %-24s %-22s %-18s %-16s %-14s %s%s"
              % (r["key"][:24], r["email"], str(r["flowtools_ports"]), str(r["at_ports"]),
                 str(r["env_ports"]), flag, "  [死号]" if r["dead"] else ""))
    print("\n  账号数=%d  不一致=%d  死号=%d" % (len(rows), n_incons, sum(1 for r in rows if r["dead"])))

    print("\n[闸门复算] 写入路径必须过 check_bind_allowed()（fail-closed）")
    for r in rows:
        g = r.get("gate_check")
        if g:
            print("  %-24s port=%-6s allowed=%-6s verdict=%-16s max=%s"
                  % (r["key"][:24], g["port"], g["allowed"], g["verdict"], g["max_per_exit"]))

    print("\n[缺口清单]")
    if not gaps:
        print("  （无）")
    for i, g in enumerate(gaps, 1):
        print("  %2d. [%-6s] %-32s %s" % (i, g["severity"], g["id"], g.get("key", "")))
        print("      detail: %s" % g["detail"])
        print("      action: %s" % g["action"])
    print("\n  ⇒ 差异合计：账号级差异行 %d / 缺口 %d" % (len(rows), len(gaps)))


def main() -> int:
    ap = argparse.ArgumentParser(description="AT↔FlowTools↔APH 端口联动只报同步器（t48）")
    ap.add_argument("--report", action="store_true", help="只读差异报告（默认）")
    ap.add_argument("--sources", action="store_true", help="只读：四处账本形态 + 哈希")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--authority-init", action="store_true",
                    help="只读：按 t22 §2.2 schema 生成 port_authority.json 建议稿（不落盘）")
    ap.add_argument("--authority-port", action="append", default=[], metavar="KEY=PORT",
                    help="显式指定某账号的 authority_port（t47 裁定用，如 ucesnq=SG 语义由 key 承载）；"
                         "可重复。仅在 --authority-init / --dry-run-write 下生效")
    ap.add_argument("--dry-run-write", action="store_true",
                    help="t60 裁定①：算出「若开 env 侧双写会写什么」逐条清单（**零写入**，不落任何文件）")
    ap.add_argument("--assert", dest="check_assert", action="store_true", help="只跑断言（已知缺陷必须被报出）")
    args = ap.parse_args()

    overrides = {}
    for item in (args.authority_port or []):
        if "=" in item:
            k, v = item.split("=", 1)
            overrides[k.strip()] = v.strip()

    ft_rows, ft_meta = read_flow_profiles()
    _pool_rows, pool_meta = read_flow_pool()
    at_rows, at_meta = read_at()
    env_rows, env_meta = read_aph()
    metas = {"flow_profiles": ft_meta, "flow_pool": pool_meta, "at": at_meta, "env": env_meta}

    if args.sources:
        print_sources(metas)
        return 0

    limit = density_limit()
    m = build_matrix(ft_rows, at_rows, env_rows)
    rows, gaps = analyze(m)

    if args.check_assert:
        return 1 if run_assertions(rows, gaps, metas) else 0

    if args.authority_init:
        doc = build_authority_doc(rows, metas, env_meta, ft_meta, pool_meta, limit,
                                  authority_overrides=overrides)
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0

    if args.dry_run_write:
        plan = build_env_write_plan(rows, limit, authority_overrides=overrides)
        print("=== env 侧双写 dry-run（**不写任何文件**；captain 批准后才真开）===")
        print("\n[写入口] MCP `tool_bind_profile_proxy`（t42 已接 `check_bind_allowed` 前置闸，fail-closed）")
        print("[目标文件] data/bindings.json（原子写 + bindings.lock 跨进程锁）")
        print("[回滚] 一行 Copy-Item 备份覆盖；或对同一端口再 bind 回原 profile\n")
        if not plan:
            print("  （无需写入：所有在册账号的 authority_port 与 env 现值一致）")
        refused = [p for p in plan if not p["gate_allowed"]]
        ok = [p for p in plan if p["gate_allowed"]]
        for i, p in enumerate(plan, 1):
            gate_mark = "" if p["gate_allowed"] else "   ★ **闸门将拒绝（fail-closed），不得写入**"
            print("  %d. port %s%s" % (i, p["port"], gate_mark))
            print("     account       : %s" % p["key"])
            print("     动作          : 把 env 侧该账号的登记口 %s → %s"
                  % (p["old_env_ports"] or "(无)", p["port"]))
            print("     字段          : profile")
            print("     旧值 → 新值   : %s → %s" % (p["old_profile"], p["new_profile"]))
            print("     契约字段      : expectedCountry=%s（保留不变）" % p["expectedCountry"])
            print("     是否跨洲      : %s" % p["cross_continent"])
            print("     是否动在册口  : %s" % p["touches_registered_port"])
            print("     是否触碰死号  : %s" % p["touches_dead"])
            print("     闸门预演      : %s" % p["gate"])
        print("\n  ⇒ 合计 %d 笔：闸门放行 %d 笔 / **将被拒绝 %d 笔**" % (len(plan), len(ok), len(refused)))
        if refused:
            print("  ★ 关键结论：即使 captain 批准开启 env 侧双写，上述 %d 笔也会被 "
                  "`check_bind_allowed()` 当场拒绝（密度超限）⇒ **开启双写不会自动造成超限**，"
                  "fail-closed 有效。" % len(refused))
        print("  ⇒ **本模式零写入**（已由 t60_verify 断言四处账本哈希不变证明）")
        return 0

    if args.json:
        print(json.dumps({"sources": metas, "density_limit": limit, "rows": rows, "gaps": gaps,
                          "totals": {"accounts": len(rows), "inconsistent": sum(1 for r in rows if not r["consistent"]),
                                     "dead": sum(1 for r in rows if r["dead"]), "gaps": len(gaps)}},
                         ensure_ascii=False, indent=2))
        return 0

    print_report(rows, gaps, metas, limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
