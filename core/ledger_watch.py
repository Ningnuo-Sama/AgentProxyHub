#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L0 只读巡检（13 项检查 + 契约守卫）：常态 0 WAN 字节。

设计红线（与 t3 `traffic-plan.md` §2.1 / §2.3 对齐）：
  R1 只允许 loopback 系统调用与文件读取；允许 SOCKS5 **greeting**（05 01 00 → 读 2 字节），
     **绝对禁止发 SOCKS5 CONNECT**（那会产生真实上游流量）。
  R2 每轮自报本轮字节数（本模块恒为 0，且会在报告里显式声明 `wan_bytes: 0`）。
  R3 只读：不写 `bindings.json` / `config.yaml` / AT 的 `gui_config.json`；
     唯一写入口是本模块自己的状态文件 `data/l0_state.json`（用于跨轮比对）。

契约守卫（用户 15 条契约的可执行形态，见 `resident-engineer-enablement.md` §5）：
  G1/G13 端口段与粘性端口不变、监听器不悬空（G7）
  G2/G3  大区锚定（跨洲/跨区跳变在 L0-12 契约三元组里报 action_required）
  G4/G5  一号一 Profile 一 IP、承载密度上限
  G6     禁用自动换绑（auto_rebind_enabled=false；计划任务命令行不得出现 --fix）
  G8     config.yaml 必须 yaml.safe_load 结构化断言，严禁 grep
  G15    不得依赖静态 proxy-group 做故障转移（AUTO-POOL 成员漂移可见）
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

try:  # t35: L0-12 需要国家码归一化（契约 ISO-2 vs 观测全名）
    from .hot_swap_executor import normalize_cc as _normalize_cc  # noqa: F401
except (ImportError, ValueError):
    try:
        from hot_swap_executor import normalize_cc as _normalize_cc  # type: ignore  # noqa: F401
    except (ImportError, ValueError):
        def _normalize_cc(value):  # type: ignore  # 兜底：至少做大小写/空白归一
            return str(value or "").strip().upper()

try:
    from .write_guard import (  # noqa: F401  (F40-1/t46：密度上限单一权威，避免两套规范)
        MAX_ACCOUNTS_PER_EXIT,
        load_dead_accounts,
        lookup_account_entry,
        read_registry,
        DEAD_ACCOUNT_REGISTRY,
    )
except (ImportError, ValueError):
    from write_guard import (  # type: ignore  # noqa: F401
        MAX_ACCOUNTS_PER_EXIT,
        load_dead_accounts,
        lookup_account_entry,
        read_registry,
        DEAD_ACCOUNT_REGISTRY,
    )
# F40-1/t46：本模块的 MAX_ACCOUNTS_PER_EXIT **就是** write_guard 那一个值（同一对象，非副本）。
_GUARD_MAX_PER_EXIT = MAX_ACCOUNTS_PER_EXIT

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APHUB_DATA_DIR") or ROOT_DIR / "data")
CONFIG_FILE = Path(os.environ.get("APHUB_CONFIG_FILE") or ROOT_DIR / "config" / "config.yaml")
L0_STATE_FILE = DATA_DIR / "l0_state.json"
AT_GUI_CONFIG = Path(os.environ.get("APHUB_AT_GUI_CONFIG") or r"C:\Users\1\.antigravity_tools\gui_config.json")

# 用户契约 ⑬：端口段不可变
FENGWO_RANGE = (21001, 21080)
XINGCHEN_RANGE = (22001, 22045)
# 用户契约 ⑤：单出口承载密度上限。
# F40-1/t46：**唯一权威 = `core/write_guard.MAX_ACCOUNTS_PER_EXIT`**（默认 2，用户 2026-10-17 裁定）。
# 此处**不得再自己赋默认值** —— 两处各写一个 default 就是 t40 查出的分叉根因。
# 收紧开关：`APHUB_MAX_ACCOUNTS_PER_EXIT=1`（在 write_guard 处生效，本处自动跟随）。
MAX_ACCOUNTS_PER_EXIT = _GUARD_MAX_PER_EXIT
SNAPSHOT_MAX_AGE_H = float(os.environ.get("APHUB_SNAPSHOT_MAX_AGE_H", "48"))
MIHOMO_API = "http://127.0.0.1:21909"

_CREATE_NO_WINDOW = 0x08000000
_HIDDEN_KW: dict[str, Any] = {}
if os.name == "nt":
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _si.wShowWindow = 0
    _HIDDEN_KW = {"startupinfo": _si, "creationflags": _CREATE_NO_WINDOW}


# ---------------------------------------------------------------- 基础工具

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return ""


def _digest_obj(value: Any) -> str:
    return _sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _decode(raw: bytes) -> str:
    """Windows 下 netstat / powershell 的 stdout 可能是 GBK(ANSI)；逐级回退解码。"""
    for encoding in ("utf-8", "gbk", "utf-16-le"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def _run(cmd: list[str], timeout: float = 20.0) -> str:
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False, **_HIDDEN_KW)
        return _decode(done.stdout or b"") + _decode(done.stderr or b"")
    except (OSError, subprocess.SubprocessError):
        return ""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _mask_server(value: str) -> str:
    """契约 ⑫：报告里不出现完整节点地址/订阅 URL，只留可核对的形状。"""
    text = str(value or "")
    try:
        ip = ipaddress.ip_address(text)
        parts = text.split(".")
        if ip.version == 4 and len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.x.x"
    except ValueError:
        pass
    return "<redacted>" if text else ""


# ---------------------------------------------------------------- 账本读取

def load_bindings() -> dict[str, Any]:
    return _read_json(DATA_DIR / "bindings.json") or {}


def load_config_struct() -> dict[str, Any]:
    """契约 ⑧：一律 yaml.safe_load 结构化解析，严禁 grep。"""
    if yaml is None:
        return {}
    try:
        return yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def load_bound_ports(bindings: Mapping[str, Any] | None = None) -> list[int]:
    """契约 ①：粘性端口 = bindings.json 的 JSON 键（端口本身绝不可变）。"""
    data = bindings if bindings is not None else load_bindings()
    ports: list[int] = []
    for key, value in (data or {}).items():
        try:
            ports.append(int(value.get("port") if isinstance(value, dict) and value.get("port") else key))
        except (TypeError, ValueError):
            continue
    return sorted(set(ports))


def _listener_map(config: Mapping[str, Any]) -> dict[int, str]:
    """端口 → 该端口实际挂的出口（mihomo listener.proxy）。契约 ① 的映射本体。"""
    out: dict[int, str] = {}
    for row in (config or {}).get("listeners") or []:
        if not isinstance(row, dict):
            continue
        try:
            port = int(row.get("port"))
        except (TypeError, ValueError):
            continue
        out[port] = str(row.get("proxy") or "")
    return out


def _proxy_index(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(p.get("name")): p for p in ((config or {}).get("proxies") or []) if isinstance(p, dict) and p.get("name")}


def _node_definition(proxy: Mapping[str, Any] | None) -> dict[str, Any]:
    """契约 ①：允许换的只有「底层节点」。定义指纹覆盖会变的部分。"""
    if not proxy:
        return {}
    return {
        "name": proxy.get("name"),
        "type": proxy.get("type"),
        "server": _mask_server(proxy.get("server")),
        "server_digest": _digest_obj(proxy.get("server")),
        "port": proxy.get("port"),
        "sni": proxy.get("servername") or proxy.get("sni"),
        "sni_digest": _digest_obj(proxy.get("servername") or proxy.get("sni")),
        "reality_pk_digest": _digest_obj((proxy.get("reality-opts") or {}).get("public-key")),
    }


# ---------------------------------------------------------------- L0 各检查

def _check_ports_listening(ports: Iterable[int]) -> dict[str, Any]:
    """L0-1 白名单端口是否 LISTENING（纯本地内核表；0 字节）。"""
    wanted = set(int(p) for p in ports)
    listening: dict[int, int] = {}
    text = _run(["netstat", "-ano", "-p", "TCP"])
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        if parts[3].upper() != "LISTENING":
            continue
        try:
            port = int(parts[1].rsplit(":", 1)[-1])
            pid = int(parts[4])
        except (ValueError, IndexError):
            continue
        if port in wanted:
            listening[port] = pid
    missing = sorted(wanted - set(listening))
    return {"ok": not missing, "listening": listening, "missing": missing}


def _check_tcp_reachable(ports: Iterable[int], timeout: float = 0.25) -> dict[str, Any]:
    """L0-2 端口 TCP 可达（loopback connect 后立即关闭；0 WAN 字节）。"""
    rows: dict[int, bool] = {}
    for port in ports:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
                rows[int(port)] = True
        except (OSError, ValueError):
            rows[int(port)] = False
    bad = sorted(p for p, ok in rows.items() if not ok)
    return {"ok": not bad, "reachable": rows, "unreachable": bad}


def _check_socks_greeting(ports: Iterable[int], timeout: float = 0.5) -> dict[str, Any]:
    """L0-3 SOCKS5 greeting（只发 05 01 00，读 2 字节；**不发 CONNECT**）。"""
    rows: dict[int, str] = {}
    for port in ports:
        verdict = "error"
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout) as sock:
                sock.settimeout(timeout)
                sock.sendall(b"\x05\x01\x00")
                reply = sock.recv(2)
                verdict = "ok" if len(reply) == 2 and reply[0] == 5 else f"bad_reply:{reply.hex()}"
        except (OSError, ValueError) as exc:
            verdict = type(exc).__name__
        rows[int(port)] = verdict
    bad = sorted(p for p, v in rows.items() if v != "ok")
    return {"ok": not bad, "greeting": rows, "bad": bad,
            "note": "greeting only, no SOCKS5 CONNECT issued (0 WAN bytes)"}


def _check_kernel_process() -> dict[str, Any]:
    """L0-4 进程存活与身份（PID + 二进制 SHA-256 + 启动时间；WMI 本地）。"""
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='mihomo.exe'\" | "
        "Select-Object ProcessId,ExecutablePath,CreationDate | ConvertTo-Json -Compress"
    )
    raw = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script])
    rows: list[dict[str, Any]] = []
    try:
        parsed = json.loads(raw.strip() or "[]")
        rows = parsed if isinstance(parsed, list) else [parsed]
    except ValueError:
        rows = []
    result: list[dict[str, Any]] = []
    for row in rows:
        exe = str(row.get("ExecutablePath") or "")
        result.append({
            "pid": row.get("ProcessId"),
            "exe": exe,
            "binary_sha256": _sha256_file(Path(exe)) if exe else "",
            "created": str(row.get("CreationDate") or ""),
        })
    return {"ok": bool(result), "kernels": result}


def _check_ledger_hashes(previous: Mapping[str, Any]) -> dict[str, Any]:
    """L0-5 账本哈希一致性（纯文件）。"""
    targets = {
        "bindings": DATA_DIR / "bindings.json",
        "autonomy_state": DATA_DIR / "autonomy_state.json",
        "config_yaml": CONFIG_FILE,
        "confidence_state": DATA_DIR / "confidence_state.json",
        "nodes": DATA_DIR / "nodes.json",
    }
    now = {name: _sha256_file(path) for name, path in targets.items()}
    prev = dict((previous or {}).get("ledger_hashes") or {})
    changed = sorted(name for name, digest in now.items() if prev.get(name) and prev.get(name) != digest)
    return {"ok": True, "hashes": now, "changed": changed, "first_run": not prev}


def _check_mapping_drift(previous: Mapping[str, Any], config: Mapping[str, Any], ports: list[int]) -> dict[str, Any]:
    """L0-6 监听→节点映射漂移（纯文件；「ampifier」类漂移的本体）。"""
    mapping = {str(p): _listener_map(config).get(p, "") for p in ports}
    digest = _digest_obj(mapping)
    prev = (previous or {}).get("listener_proxy_map") or {}
    prev_digest = (previous or {}).get("listener_proxy_digest")
    changed_ports = sorted(p for p, name in mapping.items() if str(prev.get(p, "")) != name) if prev else []
    return {"ok": not changed_ports, "map": mapping, "digest": digest,
            "prev_digest": prev_digest, "changed_ports": changed_ports}


def _check_node_definitions(previous: Mapping[str, Any], config: Mapping[str, Any], ports: list[int]) -> dict[str, Any]:
    """L0-7 节点定义漂移（同一个端口背后的落地被换）。"""
    index = _proxy_index(config)
    lmap = _listener_map(config)
    defs = {str(p): _node_definition(index.get(lmap.get(p, ""))) for p in ports}
    digests = {p: _digest_obj(d) for p, d in defs.items()}
    prev = dict((previous or {}).get("node_def_digests") or {})
    changed = sorted(p for p, d in digests.items() if prev.get(p) and prev.get(p) != d)
    return {"ok": not changed, "digests": digests, "definitions": defs, "changed_ports": changed}


def _mihomo_api(path: str, secret: str, timeout: float = 3.0) -> Any:
    request = urllib.request.Request(MIHOMO_API.rstrip("/") + path, method="GET")
    if secret:
        request.add_header("Authorization", f"Bearer {secret}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except (OSError, urllib.error.URLError, ValueError, TimeoutError):
        return None


def _check_mihomo_introspection(config: Mapping[str, Any], ports: list[int]) -> dict[str, Any]:
    """L0-8 + L0-10 mihomo 自省与业务活连接窗口（全 loopback）。"""
    secret = str((config or {}).get("secret") or "")
    version = _mihomo_api("/version", secret)
    configs = _mihomo_api("/configs", secret)
    proxies = _mihomo_api("/proxies", secret) or {}
    connections = _mihomo_api("/connections", secret) or {}
    inbound: dict[str, dict[str, float]] = {}
    for row in (connections.get("connections") or []):
        meta = row.get("metadata") or {}
        port = str(meta.get("inboundPort") or "")
        if not port:
            continue
        bucket = inbound.setdefault(port, {"download": 0.0, "upload": 0.0, "count": 0})
        bucket["download"] += float(row.get("download") or 0)
        bucket["upload"] += float(row.get("upload") or 0)
        bucket["count"] += 1
    group_rows = {}
    for name in ("AUTO-POOL", "ALL"):
        item = (proxies.get("proxies") or {}).get(name) or {}
        if item:
            group_rows[name] = {"type": item.get("type"), "now": item.get("now"),
                                "alive": item.get("alive"), "members": len(item.get("all") or [])}
    return {
        "ok": bool(version) and bool(configs),
        "version": (version or {}).get("version"),
        "configs_ok": bool(configs),
        "mode": (configs or {}).get("mode"),
        "active_connections": len(connections.get("connections") or []),
        "download_total": connections.get("downloadTotal"),
        "upload_total": connections.get("uploadTotal"),
        "inbound_by_port": {p: inbound[p] for p in sorted(inbound, key=lambda x: (len(x), x)) if p in {str(q) for q in ports} or True},
        "bound_port_activity": {str(p): inbound.get(str(p), {"count": 0, "download": 0.0, "upload": 0.0}) for p in ports},
        "groups": group_rows,
        "note": "loopback HTTP only",
    }


def _check_scheduled_tasks() -> dict[str, Any]:
    """L0-9 计划任务状态 + 契约 ⑥（命令行不得出现 --fix）。"""
    script = (
        "Get-ScheduledTask | Where-Object { $_.TaskName -like 'AgentProxyHub*' -or $_.TaskName -like 'OpenViking*' } | "
        "ForEach-Object { $i = $_ | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue; "
        "[pscustomobject]@{ name=$_.TaskName; state=[string]$_.State; last=$i.LastRunTime; "
        "result=$i.LastTaskResult; action=(($_.Actions | ForEach-Object { [string]$_.Execute + ' ' + [string]$_.Arguments }) -join ' | ') } } | "
        "ConvertTo-Json -Compress"
    )
    raw = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script])
    try:
        parsed = json.loads(raw.strip() or "[]")
        rows = parsed if isinstance(parsed, list) else [parsed]
    except ValueError:
        rows = []
    tasks: dict[str, Any] = {}
    fix_tasks: list[str] = []
    for row in rows:
        name = str(row.get("name") or "")
        action = str(row.get("action") or "")
        tasks[name] = {"state": row.get("state"), "last": str(row.get("last") or ""),
                       "result": row.get("result"), "action": action}
        if re.search(r"(^|\s)--fix(\s|$)", action):
            fix_tasks.append(name)
    return {"ok": not fix_tasks, "tasks": tasks, "with_fix_flag": fix_tasks}


def _check_snapshot_age(ports: list[int]) -> dict[str, Any]:
    """L0-11 快照新鲜度（纯文件）。"""
    state = _read_json(DATA_DIR / "confidence_state.json") or {}
    records = state.get("ports") if isinstance(state.get("ports"), dict) else state
    now = time.time()
    ages: dict[str, float | None] = {}
    for port in ports:
        rec = (records or {}).get(str(port)) or {}
        last = (rec.get("lastProbe") or {}).get("t")
        if not last:
            ages[str(port)] = None
            continue
        try:
            ages[str(port)] = round((now - float(last)) / 3600.0, 2)
        except (TypeError, ValueError):
            ages[str(port)] = None
    stale = sorted(int(p) for p, age in ages.items() if age is None or age > SNAPSHOT_MAX_AGE_H)
    return {"ok": not stale, "ages_hours": ages, "stale_ports": stale,
            "max_age_h": SNAPSHOT_MAX_AGE_H}


def _at_pool_density(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """AT 侧承载密度（契约 ④⑤）：**只输出摘要与哈希，不输出出口 URL**。

    - `accounts_per_proxy`: proxy_id → 关联账号数（1:1 契约：>1 即违规）
    - `accounts_per_exit`: 物理出口（URL 哈希）→ 关联账号数（上限 `MAX_ACCOUNTS_PER_EXIT`）
    - `shared_exit_proxies`: 同一物理出口被多个 proxy_id 复用的簇（09-29 事故的形态）
    """
    if not isinstance(raw, dict):
        return {"available": False}
    pool = ((raw.get("proxy") or {}).get("proxy_pool") or {})
    proxies = pool.get("proxies") or []
    bindings = pool.get("account_bindings") or {}
    url_by_id: dict[str, str] = {}
    for row in proxies:
        if isinstance(row, dict) and row.get("id"):
            url_by_id[str(row["id"])] = _digest_obj(row.get("url"))
    accounts_per_proxy: dict[str, int] = {}
    accounts_per_exit: dict[str, int] = {}
    accounts_by_exit: dict[str, list[str]] = {}
    for account_id, proxy_id in (bindings or {}).items():
        pid = str(proxy_id)
        accounts_per_proxy[pid] = accounts_per_proxy.get(pid, 0) + 1
        exit_digest = url_by_id.get(pid, "unknown")
        accounts_per_exit[exit_digest] = accounts_per_exit.get(exit_digest, 0) + 1
        accounts_by_exit.setdefault(exit_digest, []).append(str(account_id)[:8])
    exit_to_proxies: dict[str, list[str]] = {}
    for pid, exit_digest in url_by_id.items():
        exit_to_proxies.setdefault(exit_digest, []).append(pid)
    shared_exits = {d: sorted(p) for d, p in exit_to_proxies.items() if len(p) > 1}
    return {
        "available": True,
        "accounts_per_proxy": accounts_per_proxy,
        "accounts_per_exit": accounts_per_exit,
        "accounts_by_exit": accounts_by_exit,
        "shared_exit_proxies": shared_exits,
        "pool_size": len(proxies),
        "bindings_count": len(bindings or {}),
        "max_per_exit": MAX_ACCOUNTS_PER_EXIT,
    }


def _check_contract_triple(bindings: Mapping[str, Any], config: Mapping[str, Any], ports: list[int]) -> dict[str, Any]:
    """L0-12 契约三元组：`bindings[port].expectedCountry`（契约）vs 观测基线 vs 实际映射。

    只读；契约缺失即 fail-closed（`contract_missing`），**绝不回写契约字段**。
    """
    state = _read_json(DATA_DIR / "confidence_state.json") or {}
    records = state.get("ports") if isinstance(state.get("ports"), dict) else state
    lmap = _listener_map(config)
    rows: dict[str, Any] = {}
    problems: list[str] = []
    unknown: list[str] = []  # t35: 显式 UNKNOWN 契约单独归档
    for port in ports:
        entry = (bindings or {}).get(str(port)) or {}
        rec = (records or {}).get(str(port)) or {}
        # t35: 契约存 ISO-2（write_guard.region_of 只认 ISO-2），而 confidence_state
        # 的 baseline* 历史存**全名**（"UNITED STATES"）。直接比较**永远不等**，
        # 会把正确的契约也报成 baseline_mismatch。复用既有权威归一化
        # hot_swap_executor.normalize_cc（其 docstring 记录了 2026-10-12 同类事故）。
        contract = _normalize_cc(entry.get("expectedCountry"))
        observed_name = str(rec.get("baselineGoogleCountry") or rec.get("baselineCountry") or "").upper()
        observed = _normalize_cc(observed_name)
        mapping = lmap.get(port, "")
        row = {"contract": contract or None, "observed_baseline": observed_name or None,
               "observed_baseline_cc": observed or None, "mapping": mapping}
        # t35: 显式 UNKNOWN 是**合法但不判判**的契约：按任务口径计入
        # contract_unknown（fail-closed），既不算 contract_missing，也不算 baseline_mismatch。
        if contract in ("UNKNOWN", "UNK", "N/A"):
            row["status"] = "contract_unknown"
            row["note"] = "契约显式标 UNKNOWN：无既有归属证据，按 fail-closed 处理（需人工裁定）"
            unknown.append(f"{port}:contract_unknown")
        elif not contract:
            row["status"] = "contract_missing"
            problems.append(f"{port}:contract_missing")
        elif observed and observed != contract:
            row["status"] = "baseline_mismatch"
            problems.append(f"{port}:baseline_mismatch({observed}!={contract})")
        elif not mapped_ok(lmap, port):
            row["status"] = "mapping_missing"
            problems.append(f"{port}:mapping_missing")
        else:
            row["status"] = "ok"
        rows[str(port)] = row
    return {"ok": not problems, "rows": rows, "problems": problems,
            "contract_unknown": unknown, "contract_missing_count": len(problems),
            "contract_unknown_count": len(unknown)}


def mapped_ok(lmap: Mapping[int, str], port: int) -> bool:
    return bool(lmap.get(port))


def _check_at_bindings(previous: Mapping[str, Any]) -> dict[str, Any]:
    """L0-13 AT 账号级绑定的「字段语义指纹」（禁用整文件 SHA-256）。"""
    raw = _read_json(AT_GUI_CONFIG)
    if not isinstance(raw, dict):
        return {"ok": True, "available": False, "reason": "gui_config_unreadable"}
    pool = ((raw.get("proxy") or {}).get("proxy_pool") or {})
    bindings = pool.get("account_bindings") or {}
    semantic = {str(k): str(v) for k, v in sorted(bindings.items())}
    digest = _digest_obj(semantic)
    prev = (previous or {}).get("at_bindings_semantic")
    prev_digest = (previous or {}).get("at_bindings_semantic_digest")
    changed = sorted(k for k, v in semantic.items() if prev and str(prev.get(k)) != v)
    removed = sorted(k for k in (prev or {}) if k not in semantic) if prev else []
    return {"ok": not (changed or removed), "available": True, "digest": digest,
            "prev_digest": prev_digest, "count": len(semantic),
            "changed_accounts": changed, "removed_accounts": removed,
            "health_check_interval": pool.get("health_check_interval"),
            "pool_size": len(pool.get("proxies") or [])}


# ------------------------------------------------------- 契约守卫（G 系列）

def _guards(bindings: Mapping[str, Any], config: Mapping[str, Any], state: Mapping[str, Any],
            tasks: Mapping[str, Any], ports: list[int], at_info: Mapping[str, Any],
            mihomo: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    lmap = _listener_map(config)
    index = _proxy_index(config)
    groups = {str(g.get("name")): g for g in (config or {}).get("proxy-groups") or [] if isinstance(g, dict)}
    sw = (state or {}).get("switches") or {}

    # G7 监听器悬空（契约 ⑦：禁删 proxies[] 定义）
    dangling = sorted({str(v) for k, v in lmap.items() if v and v not in index})
    # G8 结构化断言（契约 ⑧）
    structural = {
        "proxies": len((config or {}).get("proxies") or []),
        "listeners": len((config or {}).get("listeners") or []),
        "groups": len((config or {}).get("proxy-groups") or []),
        "rules": len((config or {}).get("rules") or []),
        "dangling_listeners": dangling,
    }
    # G13 端口段（契约 ⑬）：蜂窝 21001-21080 / 星辰 22001-22045 不得变更；
    # 其它监听端口段（如 31001-31079 / 32001-32045）属既有部署，不纳入本守卫。
    fw_ports = sorted(p for p in lmap if FENGWO_RANGE[0] <= p <= FENGWO_RANGE[1])
    xc_ports = sorted(p for p in lmap if XINGCHEN_RANGE[0] <= p <= XINGCHEN_RANGE[1])
    prev_counts = (previous or {}).get("protected_range_counts") or {}
    count_drift = []
    if prev_counts:
        if prev_counts.get("fengwo") not in (None, len(fw_ports)):
            count_drift.append(f"fengwo:{prev_counts.get('fengwo')}->{len(fw_ports)}")
        if prev_counts.get("xingchen") not in (None, len(xc_ports)):
            count_drift.append(f"xingchen:{prev_counts.get('xingchen')}->{len(xc_ports)}")
    bound_outside = [p for p in ports
                     if not (FENGWO_RANGE[0] <= p <= FENGWO_RANGE[1] or XINGCHEN_RANGE[0] <= p <= XINGCHEN_RANGE[1])]
    # G1 粘性端口：绑定端口必须都真实存在 listener，且端口本身不得变
    missing_listener = [p for p in ports if p not in lmap]
    # G4/G5 一号一 Profile 一 IP + 承载密度（APH 侧 + AT 侧）
    per_port: dict[str, list[str]] = {}
    for port, entry in (bindings or {}).items():
        profile = str((entry or {}).get("profile") or "")
        if profile:
            per_port.setdefault(str(port), []).append(profile)
    profile_ports: dict[str, list[str]] = {}
    for port, profiles in per_port.items():
        for profile in profiles:
            profile_ports.setdefault(profile, []).append(port)
    multi_port_profiles = {name: sorted(set(v)) for name, v in profile_ports.items() if len(set(v)) > 1}
    exit_density: dict[str, int] = {}
    for port in ports:
        node = str(lmap.get(port, ""))
        if node:
            exit_density[node] = exit_density.get(node, 0) + len(per_port.get(str(port), []) or [1])
    dense = {name: n for name, n in exit_density.items() if n > MAX_ACCOUNTS_PER_EXIT}
    at_density = _at_pool_density(_read_json(AT_GUI_CONFIG))
    at_shared_accounts = {pid: n for pid, n in (at_density.get("accounts_per_proxy") or {}).items() if n > 1}
    at_dense_exits = {e: n for e, n in (at_density.get("accounts_per_exit") or {}).items() if n > MAX_ACCOUNTS_PER_EXIT}
    # G17 密度单调不增（契约 ③）——只能变松，不能变紧
    prev_density = dict((previous or {}).get("exit_density") or {})
    density_increase = sorted(f"{k}:{prev_density.get(k)}->{v}" for k, v in exit_density.items()
                              if prev_density.get(k) is not None and v > int(prev_density[k]))
    # G16 死号占用受保护名额（契约 ④）—— F25-2：注册表缺失/损坏必须 fail-closed 并告警
    _reg_data, _reg_status = read_registry()
    dead_registry = (_reg_data or {}).get("accounts") or {}
    _allow = list(_reg_status.get("allow_status") or [])
    dead_in_bindings: list[str] = []
    _registry_entries: dict[str, str] = {}
    for _p in profile_ports:
        _name, _entry = lookup_account_entry(_p, dead_registry)
        if _entry is None:
            continue
        _value = str((_entry or {}).get("status") if isinstance(_entry, dict) else _entry or "unknown").lower()
        _registry_entries[str(_p)] = f"{_name}:{_value}"
        if _value not in _allow:
            dead_in_bindings.append(str(_p))
    dead_in_bindings = sorted(dead_in_bindings)
    # G6 裸开关 + 计划任务命令行
    autonomy = (state or {}).get("switches") or {}
    rebind_on = bool(autonomy.get("auto_rebind_enabled"))
    # G15 静态 proxy-group 故障转移（契约 ⑮）
    url_test_groups = {name: {"type": g.get("type"), "members": len(g.get("proxies") or [])}
                       for name, g in groups.items() if str(g.get("type")) in {"url-test", "fallback", "load-balance"}}
    # G2/G3 跨区：L0-12 三元组已覆盖配置型；这里显式声明「不得依赖自动路径换区」
    g_rows = {
        "G1_sticky_port": {"ok": not missing_listener, "missing_listener": missing_listener,
                           "note": "端口由业务层锁定，只允许热替换底层节点"},
        "G2_G3_region_anchor": {"ok": True, "note": "跨洲/跨区跳变不在自动路径处理；由 L0-12 报 action_required 交人工"},
        "G4_one_profile_one_ip": {"ok": not multi_port_profiles and not at_shared_accounts,
                                  "multi_port_profiles": multi_port_profiles,
                                  "at_proxies_with_multiple_accounts": at_shared_accounts,
                                  "at_bindings_count": at_density.get("bindings_count")},
        "G5_density": {"ok": not dense and not at_dense_exits and not (at_density.get("shared_exit_proxies") or {}),
                       "max_per_exit": MAX_ACCOUNTS_PER_EXIT,
                       "aphub_exit_density": exit_density,
                       "aphub_dense_exits": dense,
                       "at_accounts_per_exit": at_density.get("accounts_per_exit"),
                       "at_dense_exits": at_dense_exits,
                       "at_shared_exit_clusters": at_density.get("shared_exit_proxies"),
                       "note": "AT 侧出口以 URL 哈希表示（契约 ⑫ 不输出出口地址）"},
        "G6_no_auto_rebind": {"ok": (not rebind_on) and not tasks.get("with_fix_flag"),
                              "auto_rebind_enabled": rebind_on,
                              "tasks_with_fix_flag": tasks.get("with_fix_flag") or []},
        "G7_no_dangling_listener": {"ok": not dangling, "dangling": dangling},
        "G8_structural_assertion": {"ok": structural["dangling_listeners"] == [] and structural["proxies"] > 0,
                                    "structural": structural, "method": "yaml.safe_load"},
        "G12_no_secret_in_report": {"ok": True, "note": "报告只含名称与 SHA-256 摘要，服务地址已掩码"},
        "G13_port_ranges": {"ok": not count_drift and not bound_outside,
                            "count_drift": count_drift, "bound_outside_protected_ranges": bound_outside,
                            "fengwo_listeners": len(fw_ports), "xingchen_listeners": len(xc_ports),
                            "allowed": [f"{FENGWO_RANGE[0]}-{FENGWO_RANGE[1]}", f"{XINGCHEN_RANGE[0]}-{XINGCHEN_RANGE[1]}"]},
        "G15_no_static_failover_reliance": {"ok": True, "advisory": True,
                                            "url_test_groups": url_test_groups,
                                            "note": "静态 proxy-group 只做粗筛；纯净备选池由驻场工程师主动维护"},
    }
    if at_info.get("available"):
        g_rows["G4_one_profile_one_ip"]["at_accounts"] = at_info.get("count")
    g_rows["G16_dead_account_not_protected"] = {
        "ok": bool(_reg_status.get("valid")) and not dead_in_bindings,
        "registry_present": bool(_reg_status.get("present")),
        "registry_valid": bool(_reg_status.get("valid")),
        "registry_reason": _reg_status.get("reason"),
        "registry_count": _reg_status.get("count"),
        "registry_allow_status": _allow,
        "registry_path": str(DEAD_ACCOUNT_REGISTRY),
        "dead_profiles_in_bindings": dead_in_bindings,
        "matched_entries": _registry_entries,
        "note": "注册表缺失/损坏即 fail-closed 并告警（不再视为「未登记」）；已登记但状态不在 allow_status 的账号不得占用受保护名额",
    }
    g_rows["G17_density_monotonic"] = {"ok": not density_increase, "density_increase": density_increase,
                                      "exit_density": exit_density}
    g_rows["G14_dual_ledger"] = {"ok": bool(bindings), "note": "bindings.json 与 CloakMulti aphub.py 共写；格式变更需两边同步"}
    g_rows["secrets_switch"] = {"hermes_notify_enabled": autonomy.get("hermes_notify_enabled"),
                                "usage_logging_enabled": autonomy.get("usage_logging_enabled"),
                                "routing_enabled": autonomy.get("routing_enabled")}
    return g_rows


# ---------------------------------------------------------------- 主入口

def _redact(value: Any) -> Any:
    """契约 ⑫：报告内不得出现密钥/Bearer/订阅 URL。"""
    if isinstance(value, dict):
        return {k: ("<redacted>" if k.lower() in {"secret", "token", "password", "authorization", "url", "subscription"}
                    else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        if re.match(r"^[a-z]+://", value):
            return "<redacted-url>"
        if len(value) >= 32 and re.fullmatch(r"[A-Za-z0-9_\-\.]+", value):
            return "<redacted-long-string>"
    return value


def collect(*, persist: bool = True) -> dict[str, Any]:
    started = time.time()
    previous = _read_json(L0_STATE_FILE) or {}
    bindings = load_bindings()
    config = load_config_struct()
    ports = load_bound_ports(bindings)
    at_info_state = _read_json(DATA_DIR / "autonomy_state.json") or {}

    l0_1 = _check_ports_listening(ports)
    l0_2 = _check_tcp_reachable(ports)
    l0_3 = _check_socks_greeting(ports)
    l0_4 = _check_kernel_process()
    l0_5 = _check_ledger_hashes(previous)
    l0_6 = _check_mapping_drift(previous, config, ports)
    l0_7 = _check_node_definitions(previous, config, ports)
    l0_8 = _check_mihomo_introspection(config, ports)
    l0_9 = _check_scheduled_tasks()
    l0_11 = _check_snapshot_age(ports)
    l0_12 = _check_contract_triple(bindings, config, ports)
    l0_13 = _check_at_bindings(previous)
    l0_10 = {"ok": True, "bound_port_activity": l0_8.get("bound_port_activity"),
             "note": "来自 L0-8 的 /connections 快照（loopback）"}

    checks = {"L0-1": l0_1, "L0-2": l0_2, "L0-3": l0_3, "L0-4": l0_4, "L0-5": l0_5, "L0-6": l0_6,
              "L0-7": l0_7, "L0-8": l0_8, "L0-9": l0_9, "L0-10": l0_10, "L0-11": l0_11,
              "L0-12": l0_12, "L0-13": l0_13}
    guards = _guards(bindings, config, at_info_state, l0_9, ports, l0_13, l0_8, previous)

    events: list[dict[str, Any]] = []
    for key, row in checks.items():
        if not row.get("ok"):
            severity = "action_required" if key in {"L0-1", "L0-2", "L0-6", "L0-7", "L0-9", "L0-12"} else "notice"
            if key == "L0-12" and all(p.endswith("contract_missing") for p in row.get("problems") or []) and row.get("problems"):
                severity = "notice"
                events.append({"type": "l0.contract_missing", "severity": "notice",
                               "detail": f"{len(row.get('problems') or [])} 个绑定口缺 expectedCountry 契约字段（纯账本前置项，不探测）"})
                continue
            detail = {k: v for k, v in row.items() if k != "ok" and not isinstance(v, (dict, list))}
            digest_fields = {k: v for k, v in row.items() if k in {"changed_ports", "missing", "unreachable", "problems", "with_fix_flag", "stale_ports"}}
            events.append({"type": f"l0.{key.lower()}_failed", "severity": severity,
                           "detail": _redact({**detail, **digest_fields})})
    for key, row in guards.items():
        if isinstance(row, dict) and row.get("ok") is False and not row.get("advisory"):
            events.append({"type": f"contract.{key}_violated", "severity": "action_required",
                           "detail": _redact({k: v for k, v in row.items() if k != "ok"})})

    ok = all(row.get("ok") for row in checks.values()) and all(
        (row.get("ok") is not False or row.get("advisory")) for row in guards.values() if isinstance(row, dict))

    report = {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "profile": "L0-readonly",
        "wan_bytes": 0,
        "paid_calls": False,
        "bindings_changed": False,
        "bound_ports": ports,
        "ok": bool(ok),
        "checks": checks,
        "guards": guards,
        "events": events,
        "duration_ms": int((time.time() - started) * 1000),
    }

    if persist:
        new_state = dict(previous)
        new_state.update({
            "version": 1,
            "updated_at": report["checked_at"],
            "bound_ports": ports,
            "ledger_hashes": l0_5["hashes"],
            "listener_proxy_map": l0_6["map"],
            "listener_proxy_digest": l0_6["digest"],
            "baseline_digest": _digest_obj({
                str(p): {k: v for k, v in ((_read_json(DATA_DIR / "confidence_state.json") or {}).get("ports") or {}).get(str(p), {}).items()
                         if str(k).startswith("baseline")} for p in ports}),
            "node_def_digests": l0_7["digests"],
            "at_bindings_semantic": {str(k): str(v) for k, v in sorted(
                (((_read_json(AT_GUI_CONFIG) or {}).get("proxy") or {}).get("proxy_pool") or {}).get("account_bindings", {}).items())},
            "at_bindings_semantic_digest": l0_13.get("digest"),
            "last_report_ok": report["ok"],
            "last_event_count": len(events),
            "exit_density": (guards.get("G5_density") or {}).get("aphub_exit_density") or {},
            "at_density_digest": _digest_obj((_at_pool_density(_read_json(AT_GUI_CONFIG)) or {}).get("accounts_per_exit") or {}),
            "guard_states": {k: v.get("ok") for k, v in guards.items() if isinstance(v, dict)},
            "protected_range_counts": {
                "fengwo": sum(1 for p in _listener_map(config) if FENGWO_RANGE[0] <= int(p) <= FENGWO_RANGE[1]),
                "xingchen": sum(1 for p in _listener_map(config) if XINGCHEN_RANGE[0] <= int(p) <= XINGCHEN_RANGE[1]),
            },
        })
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            tmp = L0_STATE_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(new_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, L0_STATE_FILE)
        except OSError:
            report["state_write_failed"] = True
    return report


def summary_line(report: Mapping[str, Any]) -> str:
    failed = [k for k, v in (report.get("checks") or {}).items() if not v.get("ok")]
    guard_failed = [k for k, v in (report.get("guards") or {}).items()
                    if isinstance(v, dict) and v.get("ok") is False and not v.get("advisory")]
    return (f"L0 ok={report.get('ok')} checks_failed={failed or '-'} "
            f"guards_failed={guard_failed or '-'} wan_bytes={report.get('wan_bytes')} "
            f"duration_ms={report.get('duration_ms')}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="AgentProxyHub L0 只读巡检（13 项 + 契约守卫，0 WAN 字节）")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告")
    parser.add_argument("--no-persist", action="store_true", help="不写 data/l0_state.json")
    parser.add_argument("--quiet", action="store_true", help="只输出一行摘要")
    args = parser.parse_args()

    report = collect(persist=not args.no_persist)
    if args.json:
        print(json.dumps(_redact(report), ensure_ascii=False, indent=2))
    elif args.quiet:
        print(summary_line(report))
    else:
        print(summary_line(report))
        for event in report["events"]:
            print(f"  [{event['severity']}] {event['type']}: {json.dumps(event['detail'], ensure_ascii=False)[:300]}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
