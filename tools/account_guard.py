#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账号出口守卫：盯住每个 Google 账号的出口国家（以 Google 自判为准）。

用法：
    python tools/account_guard.py                  # 只体检 + 告警（默认）
    python tools/account_guard.py --fix            # 额外：漂出美国的 Antigravity 账号换回美国口（受自治总闸约束）
    python tools/account_guard.py --quiet          # 无异常时不输出/不告警
    python tools/account_guard.py --probe-ttl-min 360   # 同一端口判定缓存时长（默认 360 = 6 小时）

判定标准（用户口径）：Google 自判为 United States 才算安全；其余一律报警。
换绑顺序：先在空闲口里找"谷歌判美国"的；绝不占用别的账号在用的口；每次最多换 3 个。
Flow / CloakMulti 侧不自动改写（那边有门禁与体检），只报出需要人工确认的清单。

账本权威性（2026-10-17 修复）：
    本脚本此前硬编码 ROOT = D:\\GitHub\\AgentProxyHub，导致"守护脚本读源码仓、
    内核/热替换跑运行副本"的双账本分裂——守护看到的 bindings.json 缺 21007/22003/22008，
    而热替换与 MC 保护集读的是运行副本。现改为与 core/hot_swap_executor.py 完全同源：
        运行副本目录优先（存在即用）→ 否则自探测源码仓根 → 最后回落 APHUB_DATA_DIR。
    同源后二者不会再指向不同账本；PROD_DIR 分支读到的 config.yaml 与内核 -f 指向的文件一致。

流量约束（2026-10-17 修复）：
    统一走 _google() 的 TTL 缓存（默认 6 小时/端口），绑定口只有十几个，
    单轮探测从"每 5 分钟全量"降到"每 TTL 一次"，避免近零流量约束被巡检自己破坏。
"""
from __future__ import annotations
import argparse, glob, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error

# ---------------------------------------------------------------- 账本与路径
# 与 core/hot_swap_executor.py 同源的同一套约定：运行副本优先，否则源码仓根。
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_ROOT = os.path.dirname(_HERE)
PROD_DIR = r"D:\Program Files\AgentProxyHub"
PROD_DIR = PROD_DIR if os.path.isdir(PROD_DIR) else _SRC_ROOT

ROOT = os.environ.get("APHUB_ROOT") or PROD_DIR
DATA_DIR = os.environ.get("APHUB_DATA_DIR") or os.path.join(ROOT, "data")
if PROD_DIR == _SRC_ROOT:
    # 以脚本方式直跑时，让后续从 APHUB_DATA_DIR 解析账本的模块（confidence_engine /
    # hot_swap_executor 等）看到同一个 data 目录。程序化 import 时不产生副作用。
    os.environ.setdefault("APHUB_DATA_DIR", DATA_DIR)

sys.path.insert(0, ROOT)
from core.confidence_engine import probe_google_country          # noqa: E402
from core.alert_dispatch import notify_all                        # noqa: E402

AT_BASE = r"C:\Users\1\.antigravity_tools"
STATE = os.path.join(DATA_DIR, "account_guard_state.json")
AUTONOMY_STATE = os.path.join(DATA_DIR, "autonomy_state.json")
CAND_PORTS = [p for p in range(21001, 21081)] + [p for p in range(22001, 22046)]
PROBE_TTL_S = 6 * 3600          # 同一端口 Google 判国的缓存时长
MAX_SCAN = 24                   # 单轮 find_us 最多探测的空闲口数量（流量上限）

# 手工搬运/过渡期用的工具根：预算内先看运行副本，没有再看源码仓。
_TOOLS_ROOTS = []
for _cand in (os.path.join(ROOT, "tools"), os.path.join(_SRC_ROOT, "tools")):
    if _cand not in _TOOLS_ROOTS:
        _TOOLS_ROOTS.append(_cand)


def _detect_tools_root() -> str:
    """flow_account_map.ps1 所在目录；找不到时给出双语缺失标记。"""
    for cand in _TOOLS_ROOTS:
        if os.path.isfile(os.path.join(cand, "flow_account_map.ps1")):
            return cand
    return ""


def _hidden_si():
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        return si
    return None


def sh(cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              startupinfo=_hidden_si(),
                              creationflags=0x08000000 if sys.platform == "win32" else 0).stdout
    except Exception:
        return ""


def at_key() -> str:
    return json.load(open(os.path.join(AT_BASE, "gui_config.json"), encoding="utf-8-sig"))["proxy"]["api_key"]


def at_config(key: str) -> dict:
    req = urllib.request.Request("http://127.0.0.1:8045/api/config",
                                 headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        # 兼容备用
        raw = sh(["curl.exe", "-s", "--max-time", "20", "-H", f"Authorization: Bearer {key}",
                  "http://127.0.0.1:8045/api/config"])
        return json.loads(raw) if raw else {}


def at_accounts() -> dict:
    out = {}
    for f in glob.glob(os.path.join(AT_BASE, "accounts", "*.json")):
        d = json.load(open(f, encoding="utf-8-sig"))
        if d.get("email"):
            out[d["email"]] = d.get("id") or os.path.splitext(os.path.basename(f))[0]
    return out


def flow_map() -> dict:
    tools_root = _detect_tools_root()
    if not tools_root:
        print("[account-guard] 未找到 flow_account_map.ps1（运行副本与源码仓 tools/ 均缺失），"
              "本轮 Flow 侧绑定不可见——请部署 tools/flow_account_map.ps1 后重跑")
        return {}
    raw = sh(["pwsh", "-NoProfile", "-File", os.path.join(tools_root, "flow_account_map.ps1")], timeout=60)
    try:
        rows = json.loads(raw)
    except Exception:
        return {}
    if isinstance(rows, dict):
        rows = [rows]
    return {r["email"]: r["port"] for r in rows if r.get("email") and r.get("port")}


def ledger_map() -> dict:
    try:
        d = json.load(open(os.path.join(DATA_DIR, "bindings.json"), encoding="utf-8-sig"))
    except Exception:
        return {}
    return {v.get("profile"): int(k) for k, v in d.items() if str(k).isdigit() and v.get("profile")}


def _load_state() -> dict:
    try:
        return json.load(open(STATE, encoding="utf-8-sig"))
    except Exception:
        return {}


def auto_rebind_enabled() -> bool:
    """自治总闸：autonomy_state.json 的 switches.auto_rebind_enabled。读不到一律视为关闭（fail-closed）。"""
    try:
        d = json.load(open(AUTONOMY_STATE, encoding="utf-8-sig"))
        return bool((d.get("switches") or {}).get("auto_rebind_enabled"))
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="自动把漂出美国的 Antigravity 账号换回美国口（需 auto_rebind_enabled=true）")
    ap.add_argument("--quiet", action="store_true", help="无异常时静默")
    ap.add_argument("--probe-ttl-min", type=int, default=PROBE_TTL_S // 60,
                    help="同一端口 Google 判国结果的缓存分钟数（默认 %d）" % (PROBE_TTL_S // 60))
    args = ap.parse_args()

    ttl_s = max(0, int(args.probe_ttl_min) * 60)
    key = at_key()
    cfg = at_config(key)
    pool = (cfg.get("proxy") or {}).get("proxy_pool") or {}
    proxies = pool.get("proxies") or []
    if not proxies:
        print("[account-guard] 无法读取 Antigravity 配置（gui_config.json 缺失或解析失败），跳过本轮检查")
        return 2
    url_of = {p["id"]: p["url"] for p in proxies}
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

    prev = _load_state()
    _probe_cache = {}
    for row in (prev.get("ports") or []):
        try:
            _probe_cache[int(row["port"])] = (str(row.get("google") or "FAIL"), float(row.get("probed_at") or 0))
        except (KeyError, TypeError, ValueError):
            continue

    def _probe_now(port: int) -> str:
        try:
            return probe_google_country(port, timeout=15) or "FAIL"
        except Exception:
            return "FAIL"

    def google(port: int) -> str:
        """带 TTL 缓存的 Google 判国：TTL 内复用上轮结果，避免巡检自己制造流量。"""
        hit = _probe_cache.get(port)
        if hit and ttl_s and (time.time() - hit[1]) < ttl_s:
            return hit[0]
        verdict = _probe_now(port)
        _probe_cache[port] = (verdict, time.time())
        return verdict

    problems, table = [], []
    for port in sorted(used):
        if not port:
            continue
        gc = google(port)
        who = [f"Flow:{e}" for e, p in fl.items() if p == port]
        who += [f"Antigravity:{e}" for e, p in at_by_email.items() if p == port]
        who += [f"环境:{e}" for e, p in lg.items() if p == port]
        ok = (gc == "United States")
        table.append({"port": port, "google": gc, "ok": ok, "who": who,
                      "probed_at": _probe_cache.get(port, ("", 0))[1]})
        if not ok:
            problems.append({"port": port, "google": gc, "who": who})

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    prev_bad = {p.get("port") for p in (prev.get("problems") or [])}
    cur_bad = {p["port"] for p in problems}

    # ---- 人工确认清单（结构性盲区）：account_guard 只改 Antigravity 侧，Flow/环境裸口无法自动修 ----
    manual = []
    for p in problems:
        at_hit = [aid for aid, pt in at_map.items() if pt == p["port"] and aid in email_of_id]
        if not at_hit:
            manual.append({"port": p["port"], "google": p["google"], "who": p["who"],
                           "reason": "Flow/环境侧绑定，无 Antigravity 账号锚点，脚本不会自动改写"})

    json.dump({"updated_at": stamp, "ports": table, "problems": problems,
               "manual_confirm": manual,
               "probe_ttl_s": ttl_s,
               "history": (prev.get("history") or [])[-49:] + [{"t": stamp, "bad": sorted(cur_bad)}]},
              open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if not problems:
        if not args.quiet:
            print(f"[{stamp}] 全部 {len(table)} 个账号出口均为美国，无异常")
        return 0

    lines = [f"⚠️ 账号出口异常 {len(problems)} 个（{stamp}）"]
    for p in problems:
        lines.append(f"  端口 {p['port']} 谷歌判 {p['google']}  ← " + " / ".join(p["who"][:3]))
    if manual:
        lines.append(f"  ⚠️ 其中 {len(manual)} 个属 Flow/环境侧绑定（脚本不改写，需人工确认）："
                     + ", ".join(str(m["port"]) for m in manual))
    text = "\n".join(lines)
    print(text)
    # 只在异常集合发生变化时告警，避免每 5 分钟刷屏
    if cur_bad != prev_bad:
        notify_all(text, event_id=f"acct-guard-{sorted(cur_bad)}")
    else:
        print("（异常集合与上轮相同，已跳过重复告警）")

    if not args.fix:
        print("（未开自动换绑；需要时加 --fix，且需 autonomy_state.auto_rebind_enabled=true）")
        return 1

    # ---- 自治总闸（fail-closed）：命令行 --fix 不能绕过 auto_rebind_enabled ----
    if not auto_rebind_enabled():
        print("[account-guard] 已请求 --fix，但 autonomy_state.auto_rebind_enabled=false → "
              "拒绝自动换绑（保号优先，避免自造漂移）；本轮降级为只检测并已写入 manual_confirm")
        return 1

    # ---- 自动换绑（仅 Antigravity 侧，走它自己的热重载接口）----
    def find_us(cands, need):
        """并行分批扫描，找到 need 个谷歌判美国的口就停；受 MAX_SCAN 流量上限约束。"""
        from concurrent.futures import ThreadPoolExecutor
        found = []
        scanned = 0
        for i in range(0, len(cands), 12):
            if scanned >= MAX_SCAN:
                break
            batch = cands[i:i + 12]
            scanned += len(batch)
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
    # 只处理"有 Antigravity 账号挂着"的异常口（Flow/环境侧本轮不自动改，已进 manual_confirm）
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
                                    "auth": "", "enabled": True, "priority": 0, "tags": ["gemini-pure"],
                                    "max_accounts": 1, "health_check_url": "",
                                    "last_check_time": int(time.time()), "is_healthy": True, "latency": 0})
        for aid, email in targets:
            pool["account_bindings"][aid] = pid
            fixed.append(f"{email}: {p['port']}({p['google']}) -> {cand}")
        used.add(cand)
    if fixed:
        backup = os.path.join(AT_BASE, f"gui_config.json.bak-guard-{time.strftime('%Y%m%d-%H%M')}")
        try:
            shutil.copyfile(os.path.join(AT_BASE, "gui_config.json"), backup)
        except Exception:
            pass
        body_bytes = json.dumps({"config": cfg}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:8045/api/config",
                                     data=body_bytes,
                                     headers={"Authorization": f"Bearer {key}",
                                              "Content-Type": "application/json"},
                                     method="POST")
        status_code = 0
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                status_code = resp.status
        except urllib.error.HTTPError as he:
            status_code = he.code
        except Exception:
            status_code = -1
        msg = f"🔧 已自动换回美国口（HTTP {status_code}）：\n" + "\n".join(fixed)
        print(msg)
        notify_all(msg, event_id=f"acct-guard-fix-{stamp}")
    if skipped:
        print("以下端口没有可用的美国口可换（需人工/扩容）:", skipped)
    return 1


if __name__ == "__main__":
    sys.exit(main())
