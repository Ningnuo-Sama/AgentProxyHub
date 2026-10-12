#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentProxyHub 核心探针与规则匹配引擎 (Python 实现)
支持跨平台对指定 SOCKS5 / HTTP 端口进行 Google、Claude、OpenAI 等多场景连通性诊断
"""

import sys
import os
import json
import time
import urllib.request
import urllib.error
import socket
from typing import Dict, Any, List, Optional

def test_socks5_target(host: str, port: int, target_url: str, timeout: float = 6.0) -> Dict[str, Any]:
    """通过本地代理端口真实请求目标 URL 的连通状态。

    历史缺陷（2026-10-12 体检修复）：旧实现只对本地端口做 TCP 握手就返回
    reachable=True / status_code=200，任何监听端口（哪怕内核死了代理不通）
    都会被报成"目标可达"，场景打标基于假阳性。
    """
    result = {
        "url": target_url,
        "reachable": False,
        "status_code": 0,
        "latency_ms": -1,
        "error": None
    }
    try:
        from urllib.parse import urlparse
        parsed = urlparse(target_url)
        if parsed.scheme != "https" or not parsed.hostname:
            result["error"] = f"unsupported_target: {target_url}"
            return result
        t0 = time.time()
        try:
            from .net_probe import https_get_via_socks5
        except ImportError:
            from net_probe import https_get_via_socks5
        status_code, body = https_get_via_socks5(
            int(port), parsed.hostname, parsed.path or "/", timeout=timeout)
        result["latency_ms"] = int((time.time() - t0) * 1000)
        result["status_code"] = status_code
        result["reachable"] = 200 <= status_code < 400
        if not result["reachable"]:
            result["error"] = f"http_status_{status_code}" if status_code else "probe_failed"
    except Exception as e:
        result["error"] = str(e)
    return result

def match_node_scenes(node: Dict[str, Any], scenes: List[Dict[str, Any]]) -> Dict[str, bool]:
    """依据 scenes.json 规则，对单个节点进行全场景匹配打标"""
    matched = {}
    phys_country = node.get("country") or "Unknown"
    google_country = node.get("googleCountry") or "Unknown"
    kind = node.get("kind") or "未知"
    is_dup = bool(node.get("isDuplicateIp", False))
    is_sent = bool(node.get("isSentToChina", False))
    
    for s in scenes:
        scene_id = s.get("id")
        allowed = s.get("allowedCountries") or []
        excluded = s.get("excludeCountries") or []
        req_res = bool(s.get("requireResidential", False))
        
        # 排除名单校验
        if phys_country in excluded or google_country in excluded:
            matched[scene_id] = False
            continue
            
        # 允许名单校验
        if allowed and (google_country not in allowed and phys_country not in allowed):
            matched[scene_id] = False
            continue
            
        # 住宅/家宽要求
        if req_res and kind not in ["住宅/家宽", "移动网络"]:
            matched[scene_id] = False
            continue
            
        # 重复 IP 防冲突
        if req_res and is_dup:
            matched[scene_id] = False
            continue
            
        matched[scene_id] = True
        
    return matched

if __name__ == "__main__":
    print("[AgentProxyHub Probe Engine] Ready")
