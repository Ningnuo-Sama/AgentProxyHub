#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账号出口守卫：盯住每个 Google 账号的出口国家（以 Google 自判为准）。

用法：
    python tools/account_guard.py            # 只体检 + 告警（默认）
    python tools/account_guard.py --fix      # 额外：把漂出美国的 Antigravity 账号自动换回美国口
    python tools/account_guard.py --quiet    # 无异常时不输出/不告警

判定标准（用户口径）：Google 自判为 United States 才算安全；其余一律报警。
换绑顺序：先在空闲口里找"谷歌判美国"的；绝不占用别的账号在用的口；每次最多换 3 个。
Flow / CloakMulti 侧不自动改写（那边有门禁与体检），只报出需要人工确认的清单。
"""
from __future__ import annotations
import argparse, glob, json, os, subprocess, sys, time

ROOT = r"D:\GitHub\AgentProxyHub"
sys.path.insert(0, ROOT)
from core.confidence_engine import probe_google_country          # noqa: E402
from core.alert_dispatch import notify_all                        # noqa: E402

AT_BASE = r"C:\Users\1\.antigravity_tools"
STATE = os.path.join(ROOT, "data", "account_guard_state.json")
CAND_PORTS = [p for p in range(21001, 21081)] + [p for p in range(22001, 22046)]


def sh(cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def at_key() -> str:
    return json.load(open(os.path.join(AT_BASE, "gui_config.json"), encoding="utf-8-sig"))["proxy"]["api_key"]


def at_config(key: str) -> dict:
    raw = sh(["curl.exe", "-s", "--max-time", "20", "-H", f"Authorization: Bearer {key}",
              "http://127.0.0.1:8045/api/config"])
    return json.loads(raw)


def at_accounts() -> dict:
    out = {}
    for f in glob.glob(os.path.join(AT_BASE, "accounts", "*.json")):
        d = json.load(open(f, encoding="utf-8-sig"))
        if d.get("email"):
            out[d["email"]] = d.get("id") or os.path.splitext(os.path.basename(f))[0]
    return out


def flow_map() -> dict:
    raw = sh(["pwsh", "-NoProfile", "-File", os.path.join(ROOT, "tools", "flow_account_map.ps1")], timeout=60)
    try:
        rows = json.loads(raw)
    except Exception:
        return {}
    if isinstance(rows, dict):
        rows = [rows]
    return {r["email"]: r["port"] for r in rows if r.get("email") and r.get("port")}


def ledger_map() -> dict:
    try:
        d = json.load(open(os.path.join(ROOT, "data", "bindings.json"), encoding="utf-8-sig"))
    except Exception:
        return {}
    return {v.get("profile"): int(k) for k, v in d.items() if str(k).isdigit() and v.get("profile")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="自动把漂出美国的 Antigravity 账号换回美国口")
    ap.add_argument("--quiet", action="store_true", help="无异常时静默")
    args = ap.parse_args()

    key = at_key()
    cfg = at_config(key)
    pool = cfg["proxy"]["proxy_pool"]
    url_of = {p["id"]: p["url"] for p in pool["proxies"]}
    port_of = {pid: int(u.rsplit(":", 1)[1]) for pid, u in url_of.items() if u.startswith("socks5h://")}
    at_map = {}
    for aid, pid in (pool.get("account_bindings") or {}).items():
        if pid in port_of:
            at_map[aid] = port_of[pid]
    email_of_id = {v: k for k, v in at_accounts().items()}
    at_by_email = {email_of_id[aid]: p for aid, p in at_map.items() if aid in email_of_id}

    fl = flow_map()
    lg = ledger_map()
    used = set(at_by_email.values()) | set(fl.values()) | set(lg.values())

    def google(port: int) -> str:
        try:
            return probe_google_country(port, timeout=15) or "FAIL"
        except Exception:
            return "FAIL"

    problems, table = [], []
    for port in sorted(used):
        if not port:
            continue
        gc = google(port)
        who = [f"Flow:{e}" for e, p in fl.items() if p == port]
        who += [f"Antigravity:{e}" for e, p in at_by_email.items() if p == port]
        who += [f"环境:{e}" for e, p in lg.items() if p == port]
        ok = (gc == "United States")
        table.append({"port": port, "google": gc, "ok": ok, "who": who})
        if not ok:
            problems.append({"port": port, "google": gc, "who": who})

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    prev = {}
    try:
        prev = json.load(open(STATE, encoding="utf-8-sig"))
    except Exception:
        pass
    prev_bad = {p.get("port") for p in (prev.get("problems") or [])}
    cur_bad = {p["port"] for p in problems}
    json.dump({"updated_at": stamp, "ports": table, "problems": problems,
               "history": (prev.get("history") or [])[-49:] + [{"t": stamp, "bad": sorted(cur_bad)}]},
              open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if not problems:
        if not args.quiet:
            print(f"[{stamp}] 全部 {len(table)} 个账号出口均为美国，无异常")
        return 0

    lines = [f"⚠️ 账号出口异常 {len(problems)} 个（{stamp}）"]
    for p in problems:
        lines.append(f"  端口 {p['port']} 谷歌判 {p['google']}  ← " + " / ".join(p["who"][:3]))
    text = "\n".join(lines)
    print(text)
    # 只在异常集合发生变化时告警，避免每 5 分钟刷屏
    if cur_bad != prev_bad:
        notify_all(text, event_id=f"acct-guard-{sorted(cur_bad)}")
    else:
        print("（异常集合与上轮相同，已跳过重复告警）")

    if not args.fix:
        print("（未开自动换绑；需要时加 --fix）")
        return 1

    # ---- 自动换绑（仅 Antigravity 侧，走它自己的热重载接口）----
    def find_us(cands, need):
        """并行分批扫描，找到 need 个谷歌判美国的口就停。"""
        from concurrent.futures import ThreadPoolExecutor
        found = []
        for i in range(0, len(cands), 12):
            batch = cands[i:i + 12]
            with ThreadPoolExecutor(max_workers=12) as ex:
                hits = [(p, g) for p, g in ex.map(lambda x: (x, google(x)), batch) if g == "United States"]
            for p, g in hits:
                if p not in found:
                    found.append(p)
            if len(found) >= need:
                break
        return found[:need]

    fixed, skipped = [], []
    free = [p for p in CAND_PORTS if p not in used]
    # 只处理"有 Antigravity 账号挂着"的异常口（Flow/环境侧本轮不自动改）
    fixable = [p for p in problems
               if any(aid for aid, pt in at_map.items() if pt == p["port"] and aid in email_of_id)][:5]
    spare = find_us(free, len(fixable)) if fixable else []
    for p in fixable:
        cand = spare.pop(0) if spare else None
        if cand is None:
            skipped.append(p["port"])
            continue
        free.remove(cand)
        # 受影响的 Antigravity 账号
        targets = [(aid, email_of_id[aid]) for aid, pt in at_map.items() if pt == p["port"] and aid in email_of_id]
        if not targets:
            skipped.append(p["port"])
            continue
        pid = None
        for q in pool["proxies"]:
            if q["url"].endswith(f":{cand}"):
                pid = q["id"]
                break
        if pid is None:
            pid = __import__("uuid").uuid4().hex
            pool["proxies"].append({"id": pid, "name": f"APH-美国专线-{cand}", "url": f"socks5h://127.0.0.1:{cand}",
                                    "auth": None, "enabled": True, "priority": 0, "tags": ["gemini-pure"],
                                    "max_accounts": None, "health_check_url": None,
                                    "last_check_time": int(time.time()), "is_healthy": True, "latency": None})
        for aid, email in targets:
            pool["account_bindings"][aid] = pid
            fixed.append(f"{email}: {p['port']}({p['google']}) -> {cand}")
        used.add(cand)
    if fixed:
        backup = os.path.join(AT_BASE, f"gui_config.json.bak-guard-{time.strftime('%Y%m%d-%H%M')}")
        subprocess.run(["cmd", "/c", "copy", "/y", os.path.join(AT_BASE, "gui_config.json"), backup],
                       capture_output=True)
        body = json.dumps({"config": cfg}, ensure_ascii=False)
        open(os.path.join(ROOT, "data", ".guard_post.json"), "w", encoding="utf-8").write(body)
        r = subprocess.run(["curl.exe", "-s", "-o", "NUL", "-w", "%{http_code}", "-X", "POST",
                            "-H", f"Authorization: Bearer {key}", "-H", "Content-Type: application/json",
                            "--data-binary", "@" + os.path.join(ROOT, "data", ".guard_post.json"),
                            "http://127.0.0.1:8045/api/config"], capture_output=True, text=True, timeout=40)
        os.remove(os.path.join(ROOT, "data", ".guard_post.json"))
        msg = f"🔧 已自动换回美国口（HTTP {r.stdout.strip()}）：\n" + "\n".join(fixed)
        print(msg)
        notify_all(msg, event_id=f"acct-guard-fix-{stamp}")
    if skipped:
        print("以下端口没有可用的美国口可换（需人工/扩容）:", skipped)
    return 1


if __name__ == "__main__":
    sys.exit(main())
