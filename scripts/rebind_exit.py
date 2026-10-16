#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键改绑出口端口（Antigravity Tools / Flow-Tools 两侧统一入口）。

用法：
    # Antigravity：把账号改绑到本地端口（自动建/复用池条目 + /api/config 热重载，不重启进程）
    python rebind_exit.py at you@gmail.com 21012

    # Flow：改绑账号出口并实测重锁 pinned_exit_ip（走 /api/manage/pin-exit）
    python rebind_exit.py flow you@gmail.com 21012

    # 只查看两侧当前绑定
    python rebind_exit.py show

说明：端口背后的「节点」在 AgentProxyHub 侧热替换（只换节点、不换端口），
本脚本只负责「账号 ↔ 端口」这一层的绑定。
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

AT = r"C:\Users\1\.antigravity_tools"
AT_CFG = os.path.join(AT, "gui_config.json")
AT_BASE = "http://127.0.0.1:8045"
FLOW_BASE = "http://127.0.0.1:8001"
FLOW_SETTINGS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "FlowTools", "settings.json")


def _post(url: str, payload: dict, key: str, timeout: int = 60):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _get(url: str, key: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def at_key() -> str:
    return json.load(open(AT_CFG, encoding="utf-8-sig"))["proxy"]["api_key"]


def flow_key() -> str:
    try:
        return json.load(open(FLOW_SETTINGS, encoding="utf-8-sig")).get("api_key") or "han1234"
    except Exception:
        return "han1234"


def at_show() -> None:
    key = at_key()
    cfg = _get(f"{AT_BASE}/api/config", key)
    pool = (cfg.get("proxy") or {}).get("proxy_pool") or {}
    url_of = {p["id"]: p.get("url", "") for p in pool.get("proxies") or []}
    accounts = {a["id"]: a["email"] for a in
                json.load(open(os.path.join(AT, "accounts.json"), encoding="utf-8-sig"))["accounts"]}
    print("== Antigravity 账号 ↔ 出口端口 ==")
    for aid, pid in (pool.get("account_bindings") or {}).items():
        print(f"  {accounts.get(aid, aid):<34} -> {url_of.get(pid, pid)}")


def flow_show() -> None:
    key = flow_key()
    st = _get(f"{FLOW_BASE}/api/manage/state", key)
    print("== Flow 账号 ↔ 出口端口 / 已锁出口 ==")
    for a in st.get("accounts") or []:
        print(f"  {a.get('email',''):<34} proxy={a.get('boundProxy') or a.get('bound_proxy') or '-'}"
              f"  pinned={a.get('pinnedExitIp') or a.get('pinned_exit_ip') or '-'}")


def at_bind(email: str, port: int) -> int:
    key = at_key()
    cfg = json.load(open(AT_CFG, encoding="utf-8-sig"))
    pool = cfg["proxy"]["proxy_pool"]
    accounts = {a["email"]: a["id"] for a in
                json.load(open(os.path.join(AT, "accounts.json"), encoding="utf-8-sig"))["accounts"]}
    aid = accounts.get(email)
    if not aid:
        print(f"找不到账号: {email}")
        return 2
    want = f"socks5h://127.0.0.1:{port}"
    pid = next((p["id"] for p in pool["proxies"] if p.get("url") == want), None)
    if pid is None:
        print(f"出口池里没有 {want}；请先在 AgentProxyHub 把该端口生成/导入后再改绑")
        return 3
    old = pool["account_bindings"].get(aid)
    if old == pid:
        print(f"{email} 已经绑在 {want}，无需改动")
        return 0
    pool["account_bindings"][aid] = pid
    shutil.copyfile(AT_CFG, f"{AT_CFG}.bak-rebind-{time.strftime('%Y%m%d-%H%M')}")
    code, _ = _post(f"{AT_BASE}/api/config", {"config": cfg}, key)
    print(f"{email}: {old} -> {pid}（{want}）热重载 HTTP {code}")
    return 0


def flow_bind(email: str, port: int) -> int:
    key = flow_key()
    payload = {"email": email, "boundProxy": f"socks5h://127.0.0.1:{port}"}
    try:
        code, text = _post(f"{FLOW_BASE}/api/manage/pin-exit", payload, key, timeout=90)
    except urllib.error.HTTPError as he:
        print(f"改绑失败 HTTP {he.code}: {he.read().decode('utf-8', 'replace')[:300]}")
        return 4
    print(f"{email} -> socks5h://127.0.0.1:{port}，已实测并重锁出口（HTTP {code}）: {text[:200]}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] == "show":
        at_show()
        flow_show()
        return 0
    what = args[0]
    if what == "at" and len(args) == 3:
        return at_bind(args[1], int(args[2]))
    if what == "flow" and len(args) == 3:
        return flow_bind(args[1], int(args[2]))
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
