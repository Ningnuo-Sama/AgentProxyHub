<div align="center">

<img src="https://raw.githubusercontent.com/ningnuo-dot/AgentProxyHub/main/assets/icon.png" width="128" height="128" alt="AgentProxyHub Logo" />

# AgentProxyHub

**Intelligent Multi-Port Proxy Distribution Hub Tailored for AI Agents, Anti-Detect Browsers & Multi-Account Matrices**

[![GitHub Release](https://img.shields.io/github/v/release/ningnuo-dot/AgentProxyHub?style=flat-square&color=blue)](https://github.com/ningnuo-dot/AgentProxyHub/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-slate.svg?style=flat-square)](README_EN.md)
[![MCP Ready](https://img.shields.io/badge/Protocol-Model%20Context%20Protocol%20(MCP)-purple.svg?style=flat-square)](mcp/server.py)

[中文说明](README.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)

</div>

---

### 💡 Why AgentProxyHub?

When operating multi-account matrices, anti-detect browser environments (P1, CloakMulti, AdsPower, BitBrowser), or running automated CLI agents like Claude Code, traditional proxy clients present serious bottlenecks:

1. **Single Egress Risk**: Conventional clients only expose a single local port (e.g., `7890`). Sharing one egress IP across multiple profiles triggers risk control and collective account bans.
2. **AI & Social Media Geofencing**: While nodes may open generic webpages, Anthropic blocks them via Cloudflare 1020/403, Google flags them under "China verification" (blocking Flow/Gemini), and platforms like Facebook insta-ban datacenter IPs. Testing nodes by hand is tedious.
3. **No Programmatic Agent Control**: AI agents (Claude Desktop, Cursor, local orchestrators) cannot query which local port is healthy, which IP is residential, or maintain sticky IP sessions across tasks.

**AgentProxyHub** bridges upstream Clash/Mihomo subscriptions into a dedicated local sequential port pool (SOCKS5 `20001+` / HTTP `30001+`), equipped with a **scene-based benchmark engine (`scenes.json`)** and native **Model Context Protocol (MCP)** server for human and agent synergy.

---

### ✨ Key Features

- 🔌 **One Node, Dedicated Port**: Splits upstream subscriptions into 80–120+ independent local ports (supporting dual SOCKS5 and HTTP CONNECT).
- 🎯 **Multi-Scene Benchmark Radar**:
  - **✨ Antigravity / Gemini**: Certified Google regional compliance without "routing-to-China" anomalies.
  - **🟣 Claude Exclusive**: Direct connectivity to `api.anthropic.com` free from Cloudflare blockades.
  - **🟢 ChatGPT / OpenAI**: Verified API stream compatibility and low latency.
  - **🔵 Facebook / Social Media**: Residential/broadband IP enforcement, preventing datacenter IP bans and maintaining sticky sessions.
- 🧩 **Zero-Code Extensibility (`scenes.json`)**: Adding new scenario filters (TikTok, Twitter, Amazon) requires only a few lines in `scenes.json`.
- 🤖 **Native MCP Server**: Exposes standard tools (`list_matched_proxies`, `bind_profile_proxy`, `get_proxy_command`) for Claude Desktop, Cursor, and custom autonomous agents.
- 📱 **Clientless Mobile / LAN Smart Gateway**: Built-in gateway (e.g., `192.168.0.107:39999`) allows smartphones and tablets on the same network to share optimized proxy egress without installing client apps.
- 🎨 **Minimalist Dark GUI**: Native Win11 WPF panel, system tray resident, instant response.

---

### 📦 Pre-built Release Download (Recommended)

> **No development environment setup is required! We provide ready-to-run precompiled releases.**

1. Head over to the **[GitHub Releases](https://github.com/ningnuo-dot/AgentProxyHub/releases)** page;
2. Download `AgentProxyHub-v1.0.0-windows-x64.zip`;
3. Extract to your desired directory (e.g. `D:\AgentProxyHub`);
4. Double-click **`启动AgentProxyHub.bat`** to immediately launch the control panel!

---

### 🚀 Quick Start

#### 1. Setup Subscription
Copy `config/config.example.yaml` to `config/config.yaml` and add your subscription URL:
```yaml
upstream:
  subscriptions:
    - name: "MyAirport"
      url: "https://your-airport.com/api/v1/client/subscribe?token=xxx"
      enabled: true
```

#### 2. Connect with Claude Desktop / Cursor
Add the following snippet to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "agentproxyhub": {
      "command": "python",
      "args": [
        "D:\\AgentProxyHub\\mcp\\server.py"
      ]
    }
  }
}
```
Now ask your Agent:
> *"Find the lowest latency US residential proxy and assign it to profile twitter_01."*

---

### 📄 License
This project is licensed under the [MIT License](LICENSE).
