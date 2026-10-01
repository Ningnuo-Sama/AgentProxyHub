"""Windows-user-scoped encrypted credential vault for AgentProxyHub.

Secrets are encrypted with Windows DPAPI (CurrentUser scope) and never placed in
Git, logs, MCP responses, or the metadata manifest. Originals are not deleted.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
VAULT_DIR = Path(os.environ.get("APHUB_VAULT_DIR") or r"D:\ProgramData\AgentProxyHub\credentials\vault")
MANIFEST = VAULT_DIR / "manifest.json"

class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _protect(data: bytes) -> bytes:
    crypt = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    source = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    inp = _BLOB(len(data), source)
    out = _BLOB()
    if not crypt.CryptProtectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel.LocalFree(out.pbData)


def _unprotect(data: bytes) -> bytes:
    crypt = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    source = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    inp = _BLOB(len(data), source)
    out = _BLOB()
    if not crypt.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel.LocalFree(out.pbData)


def _category(path: Path) -> str:
    name = path.name.lower()
    if "recovery" in name or "恢复码" in name:
        return "recovery_codes"
    if "google" in name or "谷歌" in path.parent.name:
        return "google_accounts"
    if "aksk" in name:
        return "cloud_aksk"
    if any(x in name for x in ("gemini", "googlekey", "antigravity")):
        return "gemini"
    if "aicost" in name:
        return "aicost"
    if "kie" in name:
        return "kie"
    if any(x in name for x in ("zhipu", "智谱", "glm")):
        return "glm"
    if any(x in name for x in ("hermes", "wechat", "weixin", "鲸管家")):
        return "notifications"
    return "uncategorized"


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".vault-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def import_directory(source: str | os.PathLike[str], *, vault_dir: Path = VAULT_DIR) -> dict[str, Any]:
    """Encrypt every file under source into the user-scoped vault."""
    root = Path(source).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    vault_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        raw = path.read_bytes()
        rel = str(path.relative_to(root)).replace("\\", "/")
        blob = _protect(raw)
        secret_id = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:24]
        target = vault_dir / (secret_id + ".dpapi")
        target.write_bytes(blob)
        entries.append({"id": secret_id, "source_name": rel, "category": _category(path),
                        "bytes": len(raw), "source_sha256": hashlib.sha256(raw).hexdigest(),
                        "blob": target.name})
    manifest = {"version": 1, "scope": "Windows DPAPI CurrentUser", "source_root": str(root),
                "secret_values_in_manifest": False, "entries": entries}
    _atomic_json(vault_dir / "manifest.json", manifest)
    return {"ok": True, "count": len(entries), "categories": sorted({e["category"] for e in entries}),
            "manifest": str(vault_dir / "manifest.json")}


def read_secret(secret_id: str, *, vault_dir: Path = VAULT_DIR) -> bytes:
    manifest = json.loads((vault_dir / "manifest.json").read_text(encoding="utf-8"))
    entry = next((e for e in manifest.get("entries", []) if e.get("id") == secret_id), None)
    if not entry:
        raise KeyError(secret_id)
    return _unprotect((vault_dir / entry["blob"]).read_bytes())


__all__ = ["VAULT_DIR", "MANIFEST", "import_directory", "read_secret"]
