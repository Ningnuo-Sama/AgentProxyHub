#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上游节点抓取与安全快照模块（P0）。

只负责：读取已登记上游、抓取 JSON/Clash 节点、规范化、去重、原子写快照。
不负责改账号绑定、不创建新监听端口、不在失败时覆盖 last-known-good。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("APHUB_DATA_DIR") or os.path.join(ROOT_DIR, "data")
UPSTREAMS_FILE = os.path.join(DATA_DIR, "upstreams.json")
SNAPSHOT_FILE = os.path.join(DATA_DIR, "upstream_nodes.json")

SUPPORTED_TYPES = {"api_token", "subscription_url", "profile_path"}
NODE_TYPES = {"anytls", "trojan", "vless", "vmess", "ss", "ss2022", "hysteria2", "tuic", "http", "socks5"}


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
    try:
        return json.loads(text)
    except ValueError:
        return text


def _simple_yaml_proxies(text: str) -> List[Dict[str, Any]]:
    """解析常见 Clash inline map；不引入 YAML 依赖，复杂 YAML 交给可选 PyYAML。"""
    result: List[Dict[str, Any]] = []
    for line in text.splitlines():
        match = re.match(r"^\s*-\s*\{(.*)\}\s*$", line)
        if not match:
            continue
        item: Dict[str, Any] = {}
        for pair in re.split(r",\s*(?=[\w-]+\s*:)", match.group(1)):
            key, sep, value = pair.partition(":")
            if not sep:
                continue
            value = value.strip().strip("'\"")
            item[key.strip()] = value
        if item:
            result.append(item)
    return result


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
    output: List[Dict[str, Any]] = []
    seen = set()
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        node_type = str(raw.get("type") or raw.get("protocol") or "").lower()
        server = raw.get("server") or raw.get("host") or raw.get("address")
        port = raw.get("port")
        if not server or not port or node_type not in NODE_TYPES:
            continue
        try:
            port = int(port)
        except (TypeError, ValueError):
            continue
        key = (str(server).lower(), port, node_type)
        if key in seen:
            continue
        seen.add(key)
        country = str(raw.get("country") or raw.get("country_code") or default_country or "").upper()
        output.append({
            "node_id": f"{provider_id}:{node_type}:{server}:{port}",
            "name": str(raw.get("name") or raw.get("ps") or f"{provider_id}-{server}:{port}"),
            "server": str(server), "port": port, "type": node_type,
            "country": country, "provider_id": provider_id,
            "health": "UNKNOWN", "confidence": 0, "veto": False,
        })
    return output


def fetch_source(source: Dict[str, Any], opener: Callable[..., Any] = urllib.request.urlopen) -> List[Dict[str, Any]]:
    provider_id = str(source.get("id") or source.get("provider_id") or "unknown")
    kind = str(source.get("type") or "api_token")
    if kind not in SUPPORTED_TYPES:
        raise ValueError(f"unsupported source type: {kind}")
    if kind == "profile_path":
        with open(str(source.get("url") or source.get("path")), "rb") as fh:
            payload = _decode_payload(fh.read())
    else:
        url = str(source.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("source url must be http(s)")
        headers = {"User-Agent": "AgentProxyHub/1.0"}
        token = str(source.get("token") or "").strip()
        if token:
            headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers)
        with opener(request, timeout=30) as response:
            payload = _decode_payload(response.read())
    country = str((source.get("extra") or {}).get("country") or "")
    return extract_nodes(payload, provider_id, country)


def write_snapshot(nodes: Iterable[Dict[str, Any]], path: str = SNAPSHOT_FILE) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"version": "1.0.0", "generatedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds"), "nodes": list(nodes)}
    fd, tmp = tempfile.mkstemp(prefix=".upstream_nodes-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def refresh_sources(sources: Iterable[Dict[str, Any]], dry_run: bool = False) -> Dict[str, Any]:
    all_nodes: List[Dict[str, Any]] = []
    reports: List[Dict[str, Any]] = []
    failures = 0
    for source in sources:
        provider_id = str(source.get("id") or "unknown")
        try:
            nodes = fetch_source(source)
            all_nodes.extend(nodes)
            reports.append({"provider_id": provider_id, "status": "ok", "fetched": len(nodes), "accepted": len(nodes)})
        except Exception as exc:
            failures += 1
            reports.append({"provider_id": provider_id, "status": "error", "fetched": 0, "accepted": 0, "error": str(exc)})
    unique = {node["node_id"]: node for node in all_nodes}
    if unique and not dry_run:
        write_snapshot(unique.values())
    return {"ok": bool(unique) or (not reports and not failures), "sources": reports, "total_nodes": len(unique), "dry_run": dry_run, "snapshot_path": None if dry_run or not unique else SNAPSHOT_FILE, "warnings": ["last-known-good 保留，未覆盖快照" ] if failures and not unique else []}


if __name__ == "__main__":
    print(json.dumps(refresh_sources(load_sources()), ensure_ascii=False, indent=2))
