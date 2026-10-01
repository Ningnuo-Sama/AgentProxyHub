#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentProxyHub MCP 端到端闭环自测试脚本
验证 JSON-RPC 2.0 握手、工具列举与核心调度能力
"""

import subprocess
import json
import sys
import os

SERVER_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")

def run_test():
    print(f"[TEST] Starting MCP server process: {SERVER_PY}")
    p = subprocess.Popen(
        [sys.executable, SERVER_PY],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8"
    )

    def send_recv(req):
        line = json.dumps(req) + "\n"
        p.stdin.write(line)
        p.stdin.flush()
        resp_line = p.stdout.readline()
        return json.loads(resp_line)

    try:
        # 1. Initialize
        print("[TEST 1/5] Testing initialize...")
        init_res = send_recv({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert init_res["result"]["serverInfo"]["name"] == "AgentProxyHub"
        print("  ✓ Initialize successful")

        # 2. tools/list
        print("[TEST 2/5] Testing tools/list...")
        list_res = send_recv({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = [t["name"] for t in list_res["result"]["tools"]]
        print(f"  ✓ Found {len(tools)} tools: {tools}")
        assert "list_scenes" in tools
        assert "list_matched_proxies" in tools
        assert "bind_profile_proxy" in tools

        # 3. tools/call: list_scenes
        print("[TEST 3/5] Testing tool call: list_scenes...")
        scenes_res = send_recv({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_scenes", "arguments": {}}
        })
        text_content = json.loads(scenes_res["result"]["content"][0]["text"])
        print(f"  ✓ Loaded scenes count: {text_content['count']}")
        assert text_content["count"] >= 4

        # 4. tools/call: list_matched_proxies (Claude scene)
        print("[TEST 4/5] Testing tool call: list_matched_proxies (scene='claude')...")
        match_res = send_recv({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "list_matched_proxies", "arguments": {"scene": "claude", "limit": 3}}
        })
        matched_content = json.loads(match_res["result"]["content"][0]["text"])
        print(f"  ✓ Matched nodes for Claude: {matched_content['total_matched']}")

        # 5. tools/call: get_proxy_command
        print("[TEST 5/7] Testing tool call: get_proxy_command (port=21008)...")
        cmd_res = send_recv({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "get_proxy_command", "arguments": {"port": 21008}}
        })
        cmd_content = json.loads(cmd_res["result"]["content"][0]["text"])
        print(f"  ✓ Generated PowerShell env: {cmd_content['powershell_env']}")
        print(f"  ✓ Generated Claude Code ready: {cmd_content['claude_code_ready']}")

        # 6. tools/call: refresh_upstream_nodes（dry-run，避免测试写入运行快照）
        print("[TEST 6/8] Testing tool call: refresh_upstream_nodes...")
        refresh_res = send_recv({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "refresh_upstream_nodes", "arguments": {"dry_run": True}}
        })
        refresh_content = json.loads(refresh_res["result"]["content"][0]["text"])
        assert refresh_content["dry_run"] is True
        print(f"  ✓ Refresh dry-run sources: {len(refresh_content['sources'])}")

        # 7. tools/call: set_upstream_credential
        print("[TEST 7/8] Testing tool call: set_upstream_credential...")
        up_res = send_recv({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "set_upstream_credential",
                "arguments": {
                    "provider_id": "test_provider",
                    "name": "测试专线源",
                    "type": "api_token",
                    "url": "https://example.com/api/v1",
                    "token": "test-jwt-token-1234567890",
                    "account": "test@example.com"
                }
            }
        })
        up_content = json.loads(up_res["result"]["content"][0]["text"])
        assert up_content["ok"] is True
        print(f"  ✓ Saved upstream: {up_content['message']}")

        # 8. tools/call: get_upstream_sources
        print("[TEST 8/8] Testing tool call: get_upstream_sources...")
        get_res = send_recv({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "get_upstream_sources", "arguments": {}}
        })
        get_content = json.loads(get_res["result"]["content"][0]["text"])
        assert get_content["ok"] is True
        assert get_content["total"] >= 1
        print(f"  ✓ Retrieved upstreams total: {get_content['total']}")

        print("\n🎉 ALL 7 MCP END-TO-END TESTS PASSED!")
    finally:
        p.terminate()

if __name__ == "__main__":
    run_test()
