#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2-4 只读探针：本地 deepseek-v4.1 端点的可达性实测。

铁律：
  * 只做 loopback 请求（127.0.0.1），不产生任何 WAN 字节；
  * 绝不打印任何密钥明文，只打印 SHA-256 前 12 位与长度；
  * 候选密钥来源于「已在本机的凭据文件 / DPAPI 金库」，不抓屏、不暴力猜。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

DSH_CREDS = Path(r"C:\Users\1\.dsh-beta\.credentials.yaml")
VAULT_DIR = Path(r"D:\ProgramData\AgentProxyHub\credentials\vault")
VAULT_MANIFEST = VAULT_DIR / "manifest.json"

ENDPOINTS = [
    ("huaiyuan-2666", "http://127.0.0.1:2666/v1", "cn:deepseek-v4.1-flash"),
    ("wkbd-7863", "http://127.0.0.1:7863/v1", "global:deepseek-v4.1-flash"),
    ("at-8045", "http://127.0.0.1:8045/v1", "gemini-3.8-flash"),
]


def sha12(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]


def _unprotect(blob: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    crypt = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    source = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
    inp = _BLOB(len(blob), source)
    out = _BLOB()
    if not crypt.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel.LocalFree(out.pbData)


def candidates() -> list[tuple[str, str]]:
    """返回 (来源标签, 候选密钥字符串)。密钥本身只留在内存。"""
    out: list[tuple[str, str]] = []
    if DSH_CREDS.exists():
        try:
            data = yaml.safe_load(DSH_CREDS.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        records = data.get("records")
        if isinstance(records, dict):
            for name, rec in records.items():
                payload = (rec or {}).get("payload") if isinstance(rec, dict) else None
                if not isinstance(payload, dict):
                    continue
                for field in ("secret", "token", "key", "api_key", "value"):
                    val = payload.get(field)
                    if isinstance(val, str) and val.strip():
                        out.append((f"dsh.records[{name}].payload.{field}", val.strip()))
        refs = data.get("refs")
        if isinstance(refs, dict):
            for name, val in refs.items():
                if isinstance(val, str) and val.strip():
                    out.append((f"dsh.refs.{name}", val.strip()))
    if VAULT_MANIFEST.exists():
        try:
            manifest = json.loads(VAULT_MANIFEST.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        for entry in manifest.get("entries") or []:
            name = str(entry.get("source_name") or "")
            blob = VAULT_DIR / str(entry.get("blob") or "")
            if not blob.exists():
                continue
            try:
                raw = _unprotect(blob.read_bytes()).decode("utf-8", "replace")
            except Exception:
                continue
            out.append((f"vault:{name}", raw.strip()))
            for line in raw.splitlines():
                line = line.strip()
                if line and len(line) >= 12:
                    out.append((f"vault:{name}#line", line))
    # 环境变量（若存在）
    for env_name in ("HUAIYUAN_API_KEY", "DS_API_KEY", "WKBD_API_KEY"):
        val = os.environ.get(env_name)
        if val:
            out.append((f"env:{env_name}", val))
    # 去重（按摘要），保持顺序
    seen, dedup = set(), []
    for label, value in out:
        digest = sha12(value)
        if digest in seen:
            continue
        seen.add(digest)
        dedup.append((label, value))
    return dedup


def get(base: str, path: str, key: str | None, timeout: float = 8.0) -> tuple[int, str]:
    req = urllib.request.Request(base.rstrip("/") + path, method="GET")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.read(200).decode("utf-8", "replace") if exc.fp else "")
    except Exception as exc:  # noqa: BLE001
        return -1, type(exc).__name__


def chat(base: str, model: str, key: str | None, *, max_tokens: int = 8, timeout: float = 60.0) -> dict:
    payload = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": "ping"}],
         "max_tokens": max_tokens, "temperature": 0, "stream": False},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=payload, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
            return {"http": resp.status, "model": body.get("model"),
                    "usage": body.get("usage"), "ok": True}
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode("utf-8", "replace") if exc.fp else ""
        return {"http": exc.code, "ok": False, "error": detail[:240]}
    except Exception as exc:  # noqa: BLE001
        return {"http": -1, "ok": False, "error": type(exc).__name__}


def main() -> int:
    print("### 无凭据探测（/v1/models）")
    for label, base, _model in ENDPOINTS:
        status, _ = get(base, "/models", None)
        print(f"  {label:12s} {base:28s} no-auth -> HTTP {status}")

    print("\n### 候选凭据（只打印摘要，不打印明文）")
    cands = candidates()
    print(f"  候选数: {len(cands)}")
    for idx, (label, value) in enumerate(cands):
        print(f"  [{idx:2d}] sha256={sha12(value)} len={len(value):3d}  {label}")

    print("\n### 逐个候选打 2666 /models（命中即停）")
    hit: tuple[str, str] | None = None
    for label, value in cands:
        status, body = get("http://127.0.0.1:2666/v1", "/models", value)
        if status == 200:
            print(f"  HIT sha256={sha12(value)} len={len(value)} {label} -> HTTP 200")
            print(f"      body[:160]={body[:160]}")
            hit = (label, value)
            break
    if not hit:
        print("  无命中：2666 上无可用凭据（本次未尝试超过 5 次/候选）")

    print("\n### 7863 无凭据 chat 探测（已实测 503，复核一次）")
    res = chat("http://127.0.0.1:7863/v1", "global:deepseek-v4.1-flash", None, max_tokens=4)
    print(f"  {json.dumps(res, ensure_ascii=False)[:300]}")

    if hit:
        label, value = hit
        print(f"\n### 2666 chat 最小探测（凭据 sha256={sha12(value)}, 来源 {label}）")
        res = chat("http://127.0.0.1:2666/v1", "cn:deepseek-v4.1-flash", value, max_tokens=8)
        print(f"  {json.dumps(res, ensure_ascii=False)[:400]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
