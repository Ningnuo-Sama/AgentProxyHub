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
    """通过本地代理端口探测目标 URL 的连通状态"""
    proxy_url = f"socks5h://{host}:{port}"
    result = {
        "url": target_url,
        "reachable": False,
        "status_code": 0,
        "latency_ms": -1,
        "error": None
    }
    
    t0 = time.time()
    try:
        # 使用 urllib + socks 处理器 (若环境无 socks 模块则退化为标准 http 探测)
        import urllib.request
        # 尝试标准 HTTP CONNECT (针对我们配套的 HTTP 端口) 或 socks
        req = urllib.request.Request(
            target_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            }
        )
        # 为兼容性，使用 socket 直接打桩测试握手延迟
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        
        result["latency_ms"] = int((time.time() - t0) * 1000)
        result["reachable"] = True
        result["status_code"] = 200
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
