#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t39 F25-1 只读发现：AT 管理 API（127.0.0.1:8045）的形状与 round-trip 保真度探测。

红线：
  * 只打 loopback（127.0.0.1:8045）；
  * 只比 SHA-256，不打印任何凭据值；配置里的疑似密钥/URL 一律脱敏；
  * `--noop-post` 才会发写请求，且发的是「GET 回来的原文（不改任何键）」——
    用于判定 POST 语义是 merge 还是 replace，同时**不改动任何键**。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8045"
GUI_CONFIG = Path(r"C:\Users\1\.antigravity_tools\gui_config.json")
DSH_CREDS = Path(r"C:\Users\1\.dsh-beta\.credentials.yaml")

REDACT_KEYS = {"secret", "token", "password", "apikey", "api_key", "authorization", "cookie", "url", "key"}


def token() -> str:
    import yaml
    data = yaml.safe_load(DSH_CREDS.read_text(encoding="utf-8")) or {}
    return str((data.get("refs") or {}).get("FD_API_KEY") or "")


def call(method: str, path: str, auth: str, body: dict | None = None, timeout: float = 8.0):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=payload, method=method)
    req.add_header("Accept", "application/json")
    if payload is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    if auth:
        req.add_header("Authorization", f"Bearer {auth}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                return resp.status, {"_raw_len": len(raw)}
    except urllib.error.HTTPError as exc:
        return exc.code, {"_error": exc.read(200).decode("utf-8", "replace")[:200]}
    except Exception as exc:  # noqa: BLE001
        return -1, {"_error": type(exc).__name__}


def redact(value):
    if isinstance(value, dict):
        return {k: ("<redacted>" if str(k).lower() in REDACT_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        if value.startswith(("http://", "https://", "socks", "vless", "vmess", "trojan", "ss://")):
            return f"<redacted-url:{len(value)}>"
        if len(value) >= 32 and re.fullmatch(r"[A-Za-z0-9_\-\.=]+", value):
            return f"<redacted-long:{len(value)}>"
    return value


def structure(value) -> dict:
    """结构指纹（键名 + 类型 + 标量原值，密钥/URL 位置记长度）。"""
    if isinstance(value, dict):
        return {k: structure(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [structure(v) for v in value]
    if isinstance(value, str):
        return {"_str_len": len(value)}
    return value


def shape(value, prefix="") -> list[str]:
    out: list[str] = []
    if isinstance(value, dict):
        for k, v in sorted(value.items()):
            out.extend(shape(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(value, list):
        out.append(f"{prefix}[] n={len(value)}")
    else:
        out.append(f"{prefix} = {value!r}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--noop-post", action="store_true", help="把 GET 回来的 config 原样 POST 回去（不改任何键）")
    parser.add_argument("--dump-shape", action="store_true", help="打印脱敏后的结构行")
    args = parser.parse_args()

    auth = token()
    print(f"FD_API_KEY sha256[:12]={hashlib.sha256(auth.encode()).hexdigest()[:12]} len={len(auth)}")
    print("--- 路由探测（无鉴权 / 有鉴权）---")
    for path in ("/api/config", "/api/nonexistent-probe", "/api/proxy/pool", "/api/proxy/config", "/api/categories"):
        s_no, _ = call("GET", path, "")
        s_yes, _ = call("GET", path, auth)
        print(f"  GET {path:24s} no-auth={s_no} with-auth={s_yes}")

    status, cfg = call("GET", "/api/config", auth)
    print(f"--- GET /api/config -> HTTP {status} ---")
    if status != 200:
        print("  无法读取服务端 config，停止。")
        return 1
    inner = cfg.get("config") if isinstance(cfg, dict) and isinstance(cfg.get("config"), dict) else cfg
    print("  顶层键:", sorted(inner.keys()) if isinstance(inner, dict) else type(inner).__name__)
    proxy = (inner or {}).get("proxy") or {}
    pool = proxy.get("proxy_pool") or {}
    print("  proxy.auto_start =", proxy.get("auto_start"))
    print("  proxy.proxy_pool.enabled =", pool.get("enabled"))
    print("  proxy.proxy_pool.auto_failover =", pool.get("auto_failover"))
    print("  proxy.proxy_pool.strategy =", pool.get("strategy"))
    print("  proxy.proxy_pool.health_check_interval =", pool.get("health_check_interval"))
    print("  proxy.proxy_pool.proxies n =", len(pool.get("proxies") or []))
    print("  proxy.proxy_pool.account_bindings n =", len(pool.get("account_bindings") or {}))
    print("  auto_sync =", (inner or {}).get("auto_sync"), " auto_refresh =", (inner or {}).get("auto_refresh"))

    file_cfg = json.loads(GUI_CONFIG.read_text(encoding="utf-8-sig"))
    srv_struct = json.dumps(structure(inner), ensure_ascii=False, sort_keys=True)
    file_struct = json.dumps(structure(file_cfg), ensure_ascii=False, sort_keys=True)
    print("--- 服务端 vs 文件 结构一致性 ---")
    print("  server structure sha256[:16] =", hashlib.sha256(srv_struct.encode()).hexdigest()[:16])
    print("  file   structure sha256[:16] =", hashlib.sha256(file_struct.encode()).hexdigest()[:16])
    print("  identical =", srv_struct == file_struct)
    srv_keys = set(shape(inner))
    file_keys = set(shape(file_cfg))
    only_srv = sorted(srv_keys - file_keys)[:15]
    only_file = sorted(file_keys - srv_keys)[:15]
    print("  仅服务端有的行:", only_srv)
    print("  仅文件有的行:", only_file)

    if args.dump_shape:
        print("--- 服务端结构（脱敏）---")
        print(json.dumps(redact(inner), ensure_ascii=False, indent=1)[:4000])

    if args.noop_post:
        print("--- NO-OP POST 回写测试（body = GET 原文，一个字都不改）---")
        status2, resp = call("POST", "/api/config", auth, {"config": inner})
        print(f"  POST /api/config -> HTTP {status2} resp={json.dumps(redact(resp), ensure_ascii=False)[:300]}")
        status3, cfg2 = call("GET", "/api/config", auth)
        inner2 = cfg2.get("config") if isinstance(cfg2, dict) and isinstance(cfg2.get("config"), dict) else cfg2
        srv_struct2 = json.dumps(structure(inner2), ensure_ascii=False, sort_keys=True)
        print("  round-trip identical =", srv_struct2 == srv_struct)
        if srv_struct2 != srv_struct:
            a, b = set(shape(inner)), set(shape(inner2))
            print("  POST 后丢失的行:", sorted(a - b)[:20])
            print("  POST 后新增的行:", sorted(b - a)[:20])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
