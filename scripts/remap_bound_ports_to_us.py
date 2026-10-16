#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Antigravity 绑定端口的后端出口节点热替换为美区（Google 判 United States）节点。

契约：只换节点、不换端口。业务端口号 21010/21012/21014/21063/21068/21076/22002 绝对不动，
仅改写 config.yaml 里 in-<port> 与 in-http-<port> 两个监听器的 `proxy:` 指向。

用法: python remap_bound_ports_to_us.py <config.yaml> <port=proxy> ...
"""
from __future__ import annotations
import io
import re
import shutil
import sys
import time


def main() -> int:
    cfg = sys.argv[1]
    pairs = {}
    for a in sys.argv[2:]:
        p, px = a.split("=", 1)
        pairs[int(p)] = px
    txt = io.open(cfg, encoding="utf-8").read()
    shutil.copyfile(cfg, f"{cfg}.bak-usremap-{time.strftime('%Y%m%d-%H%M%S')}")

    lines = txt.splitlines()
    cur = None            # 当前监听器端口
    changes = []
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*-\s*name:\s*in-(?:http-)?(\d+)\s*$", ln)
        if m:
            cur = int(m.group(1))
            continue
        if re.match(r"^\s*-\s*name:\s*", ln):      # 进入下一个监听器
            cur = None
            continue
        if cur in pairs:
            mp = re.match(r"^(\s*)proxy:\s*(\S+)\s*$", ln)
            if mp and mp.group(2) != pairs[cur]:
                changes.append((cur, mp.group(2), pairs[cur]))
                lines[i] = f"{mp.group(1)}proxy: {pairs[cur]}"

    io.open(cfg, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    for port, old, new in changes:
        print(f"in-{port}: {old} -> {new}")
    print(f"共改写 {len(changes)} 处（含 http 监听器）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
