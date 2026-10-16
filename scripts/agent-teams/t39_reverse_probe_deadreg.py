#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t39 F25-2 破坏性反向探针：把注册表临时移走，断言门禁**真的**阻断，再字节级还原。

依据经验《语料门禁合规复审》《预留键门禁同步》：
  * 严禁仅凭门禁自测全绿即判定通过 → 必须注入反例，实测阻断能力；
  * 反证结束必须比对 SHA-256 证明文件完全复原、零残留。

步骤：备份(SHA-256) → 移走注册表 → 断言 refuse_dead_account 抛 WriteRefused(registry_unavailable)
      → 断言 L0 G16 变 ok=False 且 reason=registry_missing → 还原 → 比对 SHA-256 → 复验 retired 仍被拒。
全程 0 WAN（纯本地文件操作）。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

RT = r"D:\Program Files\AgentProxyHub"
REG = Path(RT) / "data" / "dead_accounts.json"
PARKED = Path(RT) / "data" / "_dead_accounts.json.t39probe"
OUT = Path(RT) / "scratch" / "agent-teams" / "_t39_reverse_probe.json"


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    if os.path.join(RT, "core") not in sys.path:
        sys.path.insert(0, os.path.join(RT, "core"))
    spec.loader.exec_module(module)
    return module


def sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    sys.path.insert(0, RT)
    wg = _load("write_guard", os.path.join(RT, "core", "write_guard.py"))
    lw = _load("ledger_watch", os.path.join(RT, "core", "ledger_watch.py"))

    evidence: dict = {"wan_bytes": 0, "steps": []}

    baseline_hash = sha16(REG)
    evidence["baseline"] = {"path": str(REG), "sha256": baseline_hash, "bytes": REG.stat().st_size}
    print(f"[baseline] {REG} sha256={baseline_hash[:16]} bytes={REG.stat().st_size}")

    # 0) 探针前置：正常状态下 retired 号必须被拒
    try:
        wg.refuse_dead_account(profile="landinhbobbymatin")
        evidence["steps"].append({"step": "pre_registered_retired", "observed": "NOT_REFUSED"})
        print("[pre] landinhbobbymatin -> NOT_REFUSED（异常！）")
        return 1
    except wg.WriteRefused as exc:
        evidence["steps"].append({"step": "pre_registered_retired", "observed": "refused", "reason": exc.reason})
        print(f"[pre] landinhbobbymatin -> REFUSED ({exc.reason})")

    # 1) 反向探针：把注册表移走
    try:
        shutil.move(str(REG), str(PARKED))
    except OSError as exc:
        print(f"move failed: {exc}")
        return 1
    print(f"[probe] 注册表已移走 -> {PARKED.name}（此时注册表不存在）")
    try:
        # 2) 断言：缺注册表必须 fail-closed
        try:
            wg.refuse_dead_account(profile="landinhbobbymatin")
            observed = "NOT_REFUSED"
        except wg.WriteRefused as exc:
            observed = f"refused:{exc.reason}"
        evidence["steps"].append({"step": "registry_parked_refuse_dead_account", "observed": observed})
        print(f"[probe] refuse_dead_account -> {observed}")

        # 3) 断言：L0 G16 必须 ok=False 且 reason=registry_missing
        g16 = lw.collect(persist=False)["guards"]["G16_dead_account_not_protected"]
        evidence["steps"].append({"step": "registry_parked_l0_g16",
                                  "observed": {"ok": g16.get("ok"), "valid": g16.get("registry_valid"),
                                               "reason": g16.get("registry_reason")}})
        print(f"[probe] L0 G16 ok={g16.get('ok')} valid={g16.get('registry_valid')} reason={g16.get('registry_reason')}")
    finally:
        shutil.move(str(PARKED), str(REG))
        restored_hash = sha16(REG)
        evidence["restored"] = {"sha256": restored_hash, "identical": restored_hash == baseline_hash}
        print(f"[restore] sha256={restored_hash[:16]} identical={restored_hash == baseline_hash}")

    # 4) 复验：还原后 retired 仍被拒，且 G16 回到有注册表状态
    try:
        wg.refuse_dead_account(profile="landinhbobbymatin")
        after = "NOT_REFUSED"
    except wg.WriteRefused as exc:
        after = f"refused:{exc.reason}"
    g16b = lw.collect(persist=False)["guards"]["G16_dead_account_not_protected"]
    evidence["after_restore"] = {"refuse_dead_account": after, "g16_ok": g16b.get("ok"),
                                 "g16_registry_valid": g16b.get("registry_valid"),
                                 "g16_dead_in_bindings": g16b.get("dead_profiles_in_bindings")}
    print(f"[after] refuse_dead_account={after} | G16 valid={g16b.get('registry_valid')} "
          f"dead={g16b.get('dead_profiles_in_bindings')}")

    probe_ok = (evidence["steps"][1]["observed"].startswith("refused:registry_unavailable")
                and evidence["steps"][2]["observed"].get("ok") is False
                and evidence["steps"][2]["observed"].get("reason") == "registry_missing"
                and evidence["restored"]["identical"]
                and after.startswith("refused:"))
    evidence["probe_ok"] = bool(probe_ok)
    evidence["residual_files"] = [str(p) for p in (REG, PARKED) if p.exists()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"probe_ok={probe_ok}  evidence -> {OUT}")
    return 0 if probe_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
