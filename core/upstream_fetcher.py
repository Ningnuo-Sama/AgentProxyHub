#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全的上游节点抓取与 last-known-good 快照模块。"""
from __future__ import annotations

import datetime
import json
import hashlib
import ssl
from urllib.parse import urlsplit
import os
import re
import tempfile
import urllib.request
import subprocess
from typing import Any, Callable, Dict, Iterable, List

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("APHUB_DATA_DIR") or os.path.join(ROOT_DIR, "data")
UPSTREAMS_FILE = os.environ.get("APHUB_UPSTREAMS_FILE") or os.path.join(DATA_DIR, "upstreams.json")
SNAPSHOT_FILE = os.environ.get("APHUB_SNAPSHOT_FILE") or os.path.join(DATA_DIR, "upstream_nodes.json")
SUPPORTED_TYPES = {"api_token", "subscription_url", "profile_path"}
NODE_TYPES = {"anytls", "trojan", "vless", "vmess", "ss", "ss2022", "hysteria2", "tuic", "http", "socks5"}
_SECRET_KEYS = {"token", "secret", "password", "passwd", "uuid", "psk", "private_key", "private-key", "api_key", "apikey", "authorization", "headers"}


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, ValueError, TypeError):
        return default


def load_sources(path: str = UPSTREAMS_FILE) -> List[Dict[str, Any]]:
    data = _read_json(path, {})
    return list(data.get("sources") or []) if isinstance(data, dict) else []


def _decode_payload(raw: bytes) -> Any:
    text = raw.decode("utf-8-sig", errors="replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def _simple_yaml_proxies(text: str) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for line in text.splitlines():
        match = re.match(r"^\s*-\s*\{(.*)\}\s*$", line)
        if not match:
            continue
        item: Dict[str, Any] = {}
        for pair in re.split(r",\s*(?=[\w-]+\s*:)", match.group(1)):
            key, sep, value = pair.partition(":")
            if sep:
                item[key.strip()] = value.strip().strip("'\"")
        if item:
            result.append(item)
    return result


def _redact(value: Any, key: str = "") -> Any:
    """保留协议字段形状，但永不把凭据写入快照或错误响应。"""
    if key.lower().replace("_", "-") in {k.replace("_", "-") for k in _SECRET_KEYS}:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items() if str(k).lower() not in {"authorization", "proxy-authorization"}}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    return value


def extract_nodes(payload: Any, provider_id: str, default_country: str = "") -> List[Dict[str, Any]]:
    if isinstance(payload, str):
        try:
            import yaml  # type: ignore
            payload = yaml.safe_load(payload) or {}
        except ImportError:
            payload = {"proxies": _simple_yaml_proxies(payload)}
    if not isinstance(payload, dict):
        return []
    candidates = payload.get("nodes") or payload.get("proxies") or payload.get("data") or []
    if isinstance(candidates, dict):
        candidates = candidates.get("nodes") or candidates.get("proxies") or []
    if not isinstance(candidates, list):
        return []
    output, seen = [], set()
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        node_type = str(raw.get("type") or raw.get("protocol") or "").lower()
        server, port = raw.get("server") or raw.get("host") or raw.get("address"), raw.get("port")
        try:
            port = int(port)
        except (TypeError, ValueError):
            continue
        if not server or node_type not in NODE_TYPES or not 1 <= port <= 65535:
            continue
        config = dict(raw)
        config.update({"server": str(server), "port": port, "type": node_type})
        identity_config = {k: v for k, v in config.items() if k not in {"name", "ps"}}
        identity = hashlib.sha256(json.dumps(identity_config, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        key = identity
        if key in seen:
            continue
        seen.add(key)
        country = str(raw.get("country") or raw.get("country_code") or default_country or "").upper()
        output.append({
            "node_id": f"{provider_id}:{identity}",
            "name": str(raw.get("name") or raw.get("ps") or f"{provider_id}-{server}:{port}"),
            "server": str(server), "port": port, "type": node_type,
            "country": country, "provider_id": provider_id,
            "protocol_config": config,
            "health": "UNKNOWN", "confidence": 0, "veto": False,
        })
    return output


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirect rejected")


def fetch_source(source: Dict[str, Any], opener: Callable[..., Any] | None = None) -> List[Dict[str, Any]]:
    provider_id = str(source.get("id") or source.get("provider_id") or "unknown")
    kind = str(source.get("type") or "api_token")
    if kind not in SUPPORTED_TYPES:
        raise ValueError(f"unsupported source type: {kind}")
    if kind == "profile_path":
        path = str(source.get("path") or source.get("url") or "")
        with open(path, "rb") as fh:
            payload = _decode_payload(fh.read())
    else:
        extra = source.get("extra") if isinstance(source.get("extra"), dict) else {}
        url = str(extra.get("fetch_endpoint") or source.get("url") or "").strip()
        parsed = urlsplit(url)
        if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("source endpoint must use https without userinfo")
        headers = {"User-Agent": "AgentProxyHub/1.0"}
        token = str(source.get("token") or "").strip()
        if token:
            headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        # 可选本地 SOCKS5 出口：用于上游直连不可达但现有代理可达的场景。
        # 仅通过环境变量显式启用，不改变默认直连行为。
        fetch_proxy = str(os.environ.get("APHUB_UPSTREAM_SOCKS5") or "").strip()
        if fetch_proxy and opener is None:
            command = ["curl.exe", "-sS", "--fail", "--max-time", "30", "--proxy", f"socks5h://{fetch_proxy}"]
            for key, value in headers.items():
                command.extend(["-H", f"{key}: {value}"])
            command.append(url)
            result = subprocess.run(command, capture_output=True, timeout=35, creationflags=0x08000000)
            if result.returncode != 0:
                raise urllib.error.URLError("upstream proxy fetch failed")
            payload = _decode_payload(result.stdout)
        else:
            request = urllib.request.Request(url, headers=headers)
            if opener is None:
                opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())).open
            with opener(request, timeout=30) as response:
                payload = _decode_payload(response.read())
    extra = source.get("extra") if isinstance(source.get("extra"), dict) else {}
    nodes = extract_nodes(payload, provider_id, str(extra.get("country") or ""))
    if not nodes and extra.get("profile_fallback"):
        fallback = os.path.expandvars(str(extra["profile_fallback"]))
        if not os.path.isabs(fallback):
            fallback = os.path.join(ROOT_DIR, fallback)
        try:
            with open(fallback, "rb") as fh:
                nodes = extract_nodes(_decode_payload(fh.read()), provider_id, str(extra.get("country") or ""))
        except OSError:
            pass
    if not nodes:
        raise ValueError("empty or invalid node payload")
    return nodes


def _load_snapshot(path: str) -> Dict[str, Any]:
    data = _read_json(path, {})
    return data if isinstance(data, dict) and isinstance(data.get("nodes"), list) else {"version": "1.0.0", "nodes": []}


def write_snapshot(nodes: Iterable[Dict[str, Any]], path: str = SNAPSHOT_FILE, source_status: Dict[str, Any] | None = None) -> str:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    data = {"version": "1.1.0", "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"), "nodes": list(nodes)}
    if source_status is not None:
        data["source_status"] = _redact(source_status)
    fd, tmp = tempfile.mkstemp(prefix=".upstream_nodes-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def refresh_sources(sources: Iterable[Dict[str, Any]], dry_run: bool = False) -> Dict[str, Any]:
    requested = list(sources)
    old = _load_snapshot(SNAPSHOT_FILE)
    by_provider: Dict[str, List[Dict[str, Any]]] = {}
    for node in old.get("nodes", []):
        if isinstance(node, dict) and node.get("provider_id"):
            by_provider.setdefault(str(node["provider_id"]), []).append(node)
    reports, changed = [], False
    for source in requested:
        provider_id = str(source.get("id") or source.get("provider_id") or "unknown")
        try:
            nodes = fetch_source(source)
            by_provider[provider_id] = nodes
            changed = True
            reports.append({"provider_id": provider_id, "status": "ok", "fetched": len(nodes), "accepted": len(nodes)})
        except Exception as exc:
            reports.append({"provider_id": provider_id, "status": "error", "fetched": 0, "accepted": 0, "error": "上游抓取失败（详情不回传，以免泄露凭据）", "error_type": type(exc).__name__})
    merged = {n["node_id"]: n for nodes in by_provider.values() for n in nodes if isinstance(n, dict) and n.get("node_id")}
    all_failed = bool(requested) and not changed
    if changed and not dry_run:
        write_snapshot(merged.values(), SNAPSHOT_FILE, {r["provider_id"]: r["status"] for r in reports})
    return {"ok": not all_failed, "sources": reports, "total_nodes": len(merged), "dry_run": dry_run, "snapshot_path": None if dry_run or not changed else SNAPSHOT_FILE, "warnings": ["失败源保留 last-known-good"] if any(r["status"] == "error" for r in reports) else []}


if __name__ == "__main__":
    print(json.dumps(refresh_sources(load_sources()), ensure_ascii=False, indent=2))
