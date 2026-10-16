#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写动作硬门禁（refuse-first）：**拒绝执行**，不是「记一笔 / 告警 / 降分」。

背景（t26 复盘原话）：09-29 之后规范写过一次、10-17 又写一次，两次都没强制 →
「规范存在 ≠ 规范生效」。因此本模块的每个门禁都以 **抛出 `WriteRefused`** 的形式
拒绝动作本身：写路径必须 `try: guard... except WriteRefused: 放弃本次写入`，
**绝不允许「先改了再报」**。

门禁清单（对应用户契约）：
  * `refuse_cross_region_jump`     契约 ②③：跨洲/跨区跳变前置拒绝（宁可断网隔离）
  * `refuse_sticky_port_change`    契约 ①⑬：端口本身不可变，只允许换底层节点
  * `refuse_density_violation`     契约 ④⑤：一号一 Profile 一 IP；单出口承载上限
  * `refuse_missing_contract`      契约 ⑫/§2.4.1：绑定口缺 `expectedCountry` → fail-closed
  * `refuse_dead_account`          契约 ④：被封/已死账号不得占用受保护名额
  * `post_write_verify`            契约 ③：写后校验（密度单调不增 / 补登口仍在 / 契约未被改写）；不通过即回滚

**只用只读输入**：本模块不写任何生产账本；`rollback` 只在被调用方显式传入快照时恢复。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APHUB_DATA_DIR") or ROOT_DIR / "data")
DEAD_ACCOUNT_REGISTRY = DATA_DIR / "dead_accounts.json"

# ---------------------------------------------------------------- 单一权威：承载密度上限
# F40-1（t46）：密度上限此前在 **4 处**各自定义且互不相等
#   （契约 §4=2 / write_guard=1 / ledger_watch=2 / 文档「1:1」）——同一口径多处定义必再分叉。
# 收敛规则（t46 落地，captain 优选的"读单一权威"方案）：
#   * **唯一定义点 = 本文件这一行**（`write_guard` 是所有写动作门禁的入口，最靠近"拒绝执行"）；
#   * `core/ledger_watch.py` 等其它位置**只允许 import 引用**，不得再自己赋默认值；
#   * 默认值 = **2**（用户 2026-10-17 裁定「一个 IP 最多 2 个号」，权威契约
#     `docs/ACCOUNT-PROTECTION-CONTRACT.md` §4 L70）；
#   * 保留 `APHUB_MAX_ACCOUNTS_PER_EXIT=1` 收紧开关（只改严，不放宽）。
# 断言位置：`single-source-check.py` [K] 组（上限只能有一处定义，其它位置必须是引用）。
MAX_ACCOUNTS_PER_EXIT = int(os.environ.get("APHUB_MAX_ACCOUNTS_PER_EXIT", "2"))
BLOCKED_REGION_JUMP = os.environ.get("APHUB_BLOCK_CROSS_REGION", "1").lower() not in ("0", "false", "off")

REGION_MAP = {
    "US": "NA", "CA": "NA", "MX": "NA",
    "GB": "EU", "FR": "EU", "DE": "EU", "IT": "EU", "ES": "EU", "NL": "EU", "CH": "EU", "DK": "EU", "UA": "EU",
    "JP": "EA", "KR": "EA", "TW": "EA", "HK": "EA", "MO": "EA", "CN": "EA",
    "SG": "SEA", "MY": "SEA", "ID": "SEA", "TH": "SEA", "VN": "SEA", "PH": "SEA",
    "AU": "OC", "NZ": "OC", "BH": "ME", "AE": "ME", "IL": "ME", "IN": "SA", "BR": "SA",
}

# 用户契约 ② 的「宁可断网隔离」名单：命中即一律拒绝（不降级、不试探）
BLOCKED_GOOGLE_COUNTRIES = {"CN", "RU", "IR", "KP", "CU", "SY", "SD", "VE", "BY", "MM", "AF", "PK"}

# 死号注册表里只有这些状态才视为「仍可用」；其余状态（retired/banned/…）默认拒绝。
# F25-2：登记项默认拒绝 = fail-closed，避免 `status:"retired"` 这种新状态名悄悄绕过门禁。
DEFAULT_ALLOW_STATUS = ["active", "alive", "healthy", "in_use"]


class WriteRefused(Exception):
    """写动作被硬门禁拒绝。调用方必须放弃本次写入并留痕，不得继续。"""

    def __init__(self, gate: str, reason: str, detail: Mapping[str, Any] | None = None):
        super().__init__(f"{gate}: {reason}")
        self.gate = gate
        self.reason = reason
        self.detail = dict(detail or {})

    def as_dict(self) -> dict[str, Any]:
        return {"refused": True, "gate": self.gate, "reason": self.reason, "detail": self.detail}


def region_of(country: str | None) -> str:
    return REGION_MAP.get(str(country or "").upper().strip(), "UNKNOWN")


# ------------------------------------------------------------- 前置拒绝门禁

def refuse_cross_region_jump(*, expected_country: str | None, target_country: str | None,
                             port: int | None = None) -> None:
    """契约 ②③：跨洲/跨区跳变一律拒绝。**同国家**才自动放行；同大区需显式人工确认。"""
    if not BLOCKED_REGION_JUMP:
        return
    want = str(expected_country or "").upper().strip()
    got = str(target_country or "").upper().strip()
    if not want:
        raise WriteRefused("cross_region", "contract_missing: 无 expectedCountry 即拒绝换绑",
                           {"port": port, "expected": None, "target": got})
    if got in BLOCKED_GOOGLE_COUNTRIES:
        raise WriteRefused("cross_region", f"target_country_blocked: {got}（宁可断网隔离）",
                           {"port": port, "expected": want, "target": got})
    if got == want:
        return
    if region_of(got) != region_of(want):
        raise WriteRefused("cross_region", f"cross_continent: {want}->{got}",
                           {"port": port, "expected": want, "target": got,
                            "expected_region": region_of(want), "target_region": region_of(got)})
    raise WriteRefused("cross_region", f"cross_country_same_region: {want}->{got} 需人工确认",
                       {"port": port, "expected": want, "target": got, "region": region_of(want)})


def refuse_sticky_port_change(*, port: int, listener_port: int | None) -> None:
    """契约 ①⑬：端口本身不可变（业务层锁定）；只允许热替换底层节点。"""
    if listener_port is None:
        raise WriteRefused("sticky_port", f"listener_missing: 端口 {port} 无对应监听器",
                           {"port": port})
    if int(listener_port) != int(port):
        raise WriteRefused("sticky_port", f"port_renumbered: {port}->{listener_port}",
                           {"port": port, "listener_port": listener_port})


def assert_expected_ip_unique(*, expected_ip: str, exit_usage: Mapping[str, Iterable[str]],
                              self_key: str) -> None:
    """契约 ④：一号一 Profile 一 IP —— 同一出口 IP 不得被第二个 Profile 占用。"""
    ip = str(expected_ip or "").strip()
    if not ip:
        raise WriteRefused("one_profile_one_ip", "expected_ip_empty", {"self": self_key})
    holders = [str(k) for k in (exit_usage or {}).get(ip, []) if str(k) != str(self_key)]
    if holders:
        raise WriteRefused("one_profile_one_ip", f"exit_ip_shared: {ip} 已被 {holders} 占用",
                           {"ip": ip, "holders": holders, "self": self_key})


def refuse_density_violation(*, exit_key: str, existing_accounts: int,
                             limit: int = MAX_ACCOUNTS_PER_EXIT) -> None:
    """契约 ⑤：单出口承载账号数硬上限（默认 1:1）。"""
    if int(existing_accounts) >= int(limit):
        raise WriteRefused("density", f"exit_density_exceeded: {exit_key} 已有 {existing_accounts} 个账号 (limit={limit})",
                           {"exit": exit_key, "existing": existing_accounts, "limit": limit})


def refuse_missing_contract(*, port: int, contract: Mapping[str, Any] | None) -> None:
    """§2.4.1：绑定口缺 `expectedCountry` → fail-closed（**不得回退到观测基线**）。"""
    if not contract or not str((contract or {}).get("expectedCountry") or "").strip():
        raise WriteRefused("contract", f"contract_missing: 端口 {port} 无 expectedCountry",
                           {"port": port})


def read_registry(path: str | os.PathLike[str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """读取退用/封禁账号注册表 → `(data, status)`；**永不抛异常**。

    `status`：`{path, present, valid, count, reason, allow_status}`
      * 文件缺失 → `present=False, valid=False, reason=registry_missing`
      * 解析失败/结构不符 → `valid=False, reason=registry_unreadable|registry_malformed`
    """
    target = Path(path or DEAD_ACCOUNT_REGISTRY)
    status: dict[str, Any] = {"path": str(target), "present": target.exists(), "valid": False,
                              "count": 0, "reason": None,
                              "allow_status": list(DEFAULT_ALLOW_STATUS)}
    if not status["present"]:
        status["reason"] = "registry_missing"
        return {}, status
    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        status["reason"] = f"registry_unreadable:{type(exc).__name__}"
        return {}, status
    if not isinstance(raw, dict):
        status["reason"] = "registry_malformed"
        return {}, status
    entries = raw.get("accounts") if "accounts" in raw else raw.get("dead")
    if isinstance(entries, list):
        entries = {str(v): {"status": "dead"} for v in entries}
    if not isinstance(entries, dict):
        status["reason"] = "registry_malformed"
        return {}, status
    status["valid"] = True
    status["count"] = len(entries)
    status["allow_status"] = [str(s).lower() for s in (raw.get("allow_status") or DEFAULT_ALLOW_STATUS)]
    return {"raw": raw, "accounts": entries}, status


def load_dead_accounts(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """兼容入口：返回注册表原始 dict（缺失/损坏 → `{}`）。判定请用 `read_registry`/`refuse_dead_account`。"""
    data, _status = read_registry(path)
    return (data or {}).get("raw") or {}


def registry_status(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    return read_registry(path)[1]


def lookup_account_entry(profile: str, entries: Mapping[str, Any]) -> tuple[str | None, Any]:
    """按精确名字或 `aliases` 精确匹配（**不做模糊匹配**，避免误伤其它账号）。"""
    key = str(profile)
    if key in (entries or {}):
        return key, entries[key]
    for name, entry in (entries or {}).items():
        if isinstance(entry, dict) and key in [str(a) for a in (entry.get("aliases") or [])]:
            return str(name), entry
    return None, None


def refuse_dead_account(*, profile: str, registry: Mapping[str, Any] | None = None,
                        registry_path: str | os.PathLike[str] | None = None) -> None:
    """契约 ④：被封/已死账号不得占用受保护名额（入池、补登、换绑前置校验）。

    **fail-closed 两点**（F25-2）：
      1. **注册表缺失/损坏 → 拒绝**（`registry_unavailable`），绝不静默放行；
      2. 登记项**默认拒绝**：只有 `status` 显式落在 `allow_status`（默认 active/alive/healthy/in_use）才放行，
         `retired`/`banned`/`tosterminated` 等一律拒绝（新状态名不会悄悄绕过）。
    """
    if registry is not None:
        entries = registry.get("accounts") if "accounts" in registry else registry.get("dead")
        if isinstance(entries, list):
            entries = {str(v): {"status": "dead"} for v in entries}
        entries = entries if isinstance(entries, dict) else {}
        allow = [str(s).lower() for s in (registry.get("allow_status") or DEFAULT_ALLOW_STATUS)]
    else:
        data, status = read_registry(registry_path)
        if not status.get("valid"):
            raise WriteRefused("dead_account", f"registry_unavailable: {status.get('reason')}",
                               {"registry": status.get("path"), "reason": status.get("reason"),
                                "note": "注册表缺失/损坏即 fail-closed，禁止静默放行"})
        entries = (data or {}).get("accounts") or {}
        allow = list(status.get("allow_status") or DEFAULT_ALLOW_STATUS)

    name, entry = lookup_account_entry(profile, entries)
    if entry is None:
        return  # 未登记：不臆造号状态（t30 待裁定范围内按「未登记」处理）
    value = str(entry.get("status") if isinstance(entry, dict) else entry or "unknown").lower()
    if value in allow:
        return
    raise WriteRefused("dead_account", f"account_not_alive: {profile} ({value})",
                       {"profile": profile, "registry_key": name, "status": value,
                        "evidence": (entry or {}).get("evidence") if isinstance(entry, dict) else None,
                        "adjudicated_by": (entry or {}).get("adjudicated_by") if isinstance(entry, dict) else None})


# ------------------------------------------------------------- 写后校验

def post_write_verify(*, before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """契约 ③：写动作后置校验。任一项不通过 → `ok=False`，调用方必须回滚。

    校验项：
      P1 单出口承载账号数**单调不增**（密度只能变松，不能变紧）
      P2 补登口仍在（before 里的绑定端口集合 ⊆ after）
      P3 契约未被改写（`expectedCountry` 逐口一致）
      P4 端口号未变（粘性端口契约）
      P5 跨洲跳变未发生（若 after 提供了 country）
    """
    problems: list[dict[str, Any]] = []

    def density(snapshot: Mapping[str, Any]) -> dict[str, int]:
        rows = snapshot.get("exit_density") or {}
        return {str(k): int(v) for k, v in rows.items()}

    db, da = density(before), density(after)
    for exit_key, count in da.items():
        if count > int(db.get(exit_key, 0)):
            problems.append({"id": "P1_density_increased", "exit": exit_key,
                             "before": db.get(exit_key, 0), "after": count})

    before_ports = {str(p) for p in (before.get("bound_ports") or [])}
    after_ports = {str(p) for p in (after.get("bound_ports") or [])}
    lost = sorted(before_ports - after_ports)
    if lost:
        problems.append({"id": "P2_backfilled_port_lost", "ports": lost})

    bc = {str(k): str((v or {}).get("expectedCountry") or "") for k, v in (before.get("contracts") or {}).items()}
    ac = {str(k): str((v or {}).get("expectedCountry") or "") for k, v in (after.get("contracts") or {}).items()}
    changed = sorted(k for k in bc if bc[k] != ac.get(k, ""))
    if changed:
        problems.append({"id": "P3_contract_rewritten", "ports": changed})

    port_changes = sorted(k for k, v in (after.get("port_numbers") or {}).items()
                          if str(before.get("port_numbers", {}).get(k, v)) != str(v))
    if port_changes:
        problems.append({"id": "P4_port_renumbered", "ports": port_changes})

    for port, want in (after.get("expected_country_by_port") or {}).items():
        got = (after.get("observed_country_by_port") or {}).get(port)
        if got and str(got).upper() != str(want).upper() and region_of(got) != region_of(want):
            problems.append({"id": "P5_cross_region_after_write", "port": port,
                             "expected": want, "observed": got})

    return {"ok": not problems, "problems": problems,
            "rollback_required": bool(problems),
            "checked": ["P1_density_monotonic", "P2_backfill_preserved", "P3_contract_untouched",
                        "P4_ports_unchanged", "P5_no_cross_region"]}


def rollback_from_snapshot(*, snapshot_path: str | os.PathLike[str], target_path: str | os.PathLike[str],
                           confirm: bool = False) -> dict[str, Any]:
    """按**内容**回滚（不依赖文件名时间戳）。必须显式 `confirm=True`。"""
    if not confirm:
        return {"ok": False, "code": "confirm_required",
                "note": "回滚是写动作；必须显式确认（对应契约 ⑪ 的打断确认项）"}
    src, dst = Path(snapshot_path), Path(target_path)
    if not src.exists():
        return {"ok": False, "code": "snapshot_missing", "snapshot": str(src)}
    backup = dst.with_suffix(dst.suffix + ".pre-rollback")
    try:
        if dst.exists():
            backup.write_bytes(dst.read_bytes())
        tmp = dst.with_suffix(dst.suffix + ".rollback.tmp")
        tmp.write_bytes(src.read_bytes())
        os.replace(tmp, dst)
        return {"ok": True, "restored_from": str(src), "target": str(dst),
                "previous_preserved_at": str(backup)}
    except OSError as exc:
        return {"ok": False, "code": "rollback_failed", "error": str(exc)[:200]}


# ------------------------------------------------------------------ 自检

def self_test() -> dict[str, Any]:
    """门禁形态自检：违例必须「抛异常拒绝」，软返回即视为门禁失效。

    F25-2 追加：**注册表缺失必须 refused**（fail-closed）、`status:"retired"` 必须 refused、
    同注册表内 `status:"active"` 必须放行。
    """
    import tempfile

    cases: list[tuple[str, str, str]] = []  # (name, expectation, observed)

    def case(name: str, expect: str, fn) -> None:
        try:
            fn()
            observed = "NOT_REFUSED"
        except WriteRefused:
            observed = "refused"
        except Exception as exc:  # noqa: BLE001
            observed = f"unexpected:{type(exc).__name__}"
        cases.append((name, expect, observed))

    case("cross_continent", "refused",
         lambda: refuse_cross_region_jump(expected_country="US", target_country="UA", port=21013))
    case("cross_same_region_other_country", "refused",
         lambda: refuse_cross_region_jump(expected_country="US", target_country="CA", port=21013))
    case("blocked_country", "refused",
         lambda: refuse_cross_region_jump(expected_country="US", target_country="CN", port=21013))
    case("same_country_allowed", "NOT_REFUSED",
         lambda: refuse_cross_region_jump(expected_country="US", target_country="US", port=21013))
    case("sticky_port_renumber", "refused", lambda: refuse_sticky_port_change(port=21013, listener_port=21014))
    case("sticky_port_missing", "refused", lambda: refuse_sticky_port_change(port=21013, listener_port=None))
    # F40-1/t46：密度上限单一权威 = 2。这里同时验「=2 默认」与「=1 收紧开关」两侧语义，
    # 并把**默认值本身**纳入自检（防止再次分叉回 1）。
    case("density_at_limit_2_refused", "refused",
         lambda: refuse_density_violation(exit_key="fw-21075", existing_accounts=2, limit=2))
    case("density_below_limit_2_allowed", "NOT_REFUSED",
         lambda: refuse_density_violation(exit_key="fw-21075", existing_accounts=1, limit=2))
    case("density_tightened_to_1_refused", "refused",
         lambda: refuse_density_violation(exit_key="fw-21075", existing_accounts=1, limit=1))

    def _density_default_must_be_2() -> None:
        if int(MAX_ACCOUNTS_PER_EXIT) != 2:
            raise WriteRefused("density",
                               f"default_drifted: MAX_ACCOUNTS_PER_EXIT={MAX_ACCOUNTS_PER_EXIT} != 2")

    # 期望 NOT_REFUSED = 正向断言「默认值确实是 2」；若漂移回 1，该函数会抛 WriteRefused，
    # 于是 observed=refused ≠ expected ⇒ 自检失败（这就是我们要的报警方向）。
    case("density_default_is_2_not_1", "NOT_REFUSED", _density_default_must_be_2)
    case("missing_contract", "refused", lambda: refuse_missing_contract(port=21013, contract=None))
    case("shared_exit_ip", "refused",
         lambda: assert_expected_ip_unique(expected_ip="203.0.113.10",
                                           exit_usage={"203.0.113.10": ["flow_a", "flow_b"]},
                                           self_key="flow_c"))
    # ---- 死号门禁（F25-2 新增用例）------------------------------------------
    case("dead_account_banned", "refused",
         lambda: refuse_dead_account(profile="flow_dead",
                                     registry={"accounts": {"flow_dead": {"status": "banned"}}}))
    case("dead_account_retired", "refused",
         lambda: refuse_dead_account(profile="landinhbobbymatin",
                                     registry={"accounts": {"landinhbobbymatin": {"status": "retired"}}}))
    case("dead_account_alias_match", "refused",
         lambda: refuse_dead_account(profile="flow_landinhbobbymatin",
                                     registry={"accounts": {"landinhbobbymatin": {
                                         "status": "retired", "aliases": ["flow_landinhbobbymatin"]}}}))
    case("dead_account_unknown_status_opaque", "refused",
         lambda: refuse_dead_account(profile="mystery", registry={"accounts": {"mystery": {"status": "on_hold"}}}))
    case("alive_account_allowed", "NOT_REFUSED",
         lambda: refuse_dead_account(profile="flow_ok", registry={"accounts": {"flow_ok": {"status": "active"}}}))
    case("unregistered_account_allowed", "NOT_REFUSED",
         lambda: refuse_dead_account(profile="nobody", registry={"accounts": {"someone": {"status": "retired"}}}))

    with tempfile.TemporaryDirectory(prefix="wg-deadreg-") as tmp:
        missing = Path(tmp) / "dead_accounts.json"
        case("dead_registry_missing_fail_closed", "refused",
             lambda: refuse_dead_account(profile="anyone", registry_path=missing))
        broken = Path(tmp) / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        case("dead_registry_malformed_fail_closed", "refused",
             lambda: refuse_dead_account(profile="anyone", registry_path=broken))
        real = Path(tmp) / "real.json"
        real.write_text(json.dumps({"version": 1, "accounts": {"landinhbobbymatin": {"status": "retired"}}}),
                        encoding="utf-8")
        case("dead_registry_real_file_refuses_retired", "refused",
             lambda: refuse_dead_account(profile="landinhbobbymatin", registry_path=real))
        case("dead_registry_real_file_allows_unregistered", "NOT_REFUSED",
             lambda: refuse_dead_account(profile="not_listed", registry_path=real))

    post = post_write_verify(
        before={"exit_density": {"fw-21075": 1}, "bound_ports": [21013], "contracts": {"21013": {"expectedCountry": "US"}}},
        after={"exit_density": {"fw-21075": 2}, "bound_ports": [21013], "contracts": {"21013": {"expectedCountry": "US"}}},
    )
    post_ok = post["ok"] is False and post["problems"][0]["id"] == "P1_density_increased"
    mismatches = [c for c in cases if c[1] != c[2]]
    reg = registry_status()
    return {"ok": not mismatches and post_ok,
            "gates": {name: {"expected": exp, "observed": obs} for name, exp, obs in cases},
            "mismatches": mismatches,
            "case_count": len(cases),
            "registry": {k: v for k, v in reg.items() if k != "allow_status"},
            "post_write_verify": post,
            "note": "门禁必须抛 WriteRefused；软返回即视为门禁失效；注册表缺失必须 refused"}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="写动作硬门禁（refuse-first）自检 / 单次校验")
    parser.add_argument("--self-test", action="store_true", help="运行门禁形态自检")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        result = self_test()
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"write_guard self-test ok={result['ok']} cases={result['case_count']} "
                  f"mismatches={result['mismatches']}")
            for name, row in (result["gates"] or {}).items():
                flag = "OK " if row["expected"] == row["observed"] else "BAD"
                print(f"  [{flag}] {name:44s} expected={row['expected']:12s} observed={row['observed']}")
            print(f"  registry: {result['registry']}")
        return 0 if result["ok"] else 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
