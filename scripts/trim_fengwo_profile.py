#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""裁掉蜂窝订阅里的套餐元信息行（剩余流量/重置/到期/续费/商城），
使有效节点数落回 80 以内，满足 gen-config.ps1 的 21001-21080 红线段断言。

用法: python trim_fengwo_profile.py <源yaml> <目标yaml>
"""
from __future__ import annotations
import re
import sys

META = ("剩余流量", "距离下次重置", "套餐到期", "续费", "商城")


def main() -> int:
    src, dst = sys.argv[1], sys.argv[2]
    extra = tuple(sys.argv[3:])
    patterns = META + extra
    with open(src, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    out, dropped = [], []
    for ln in lines:
        s = ln.strip()
        if s.startswith("- {") and any(m in s for m in patterns):
            dropped.append(s[:60])
            continue
        out.append(ln)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    total = sum(1 for ln in out if ln.strip().startswith("- {"))
    print(f"源行数={len(lines)} 保留={len(out)} 丢弃元信息={len(dropped)} 有效节点行={total}")
    for d in dropped:
        print("   丢弃:", d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
