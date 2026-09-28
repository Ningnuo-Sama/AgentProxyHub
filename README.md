<div align="center">

<img src="https://raw.githubusercontent.com/ningnuo-dot/AgentProxyHub/main/assets/icon.png" width="128" height="128" alt="AgentProxyHub Logo" />

# AgentProxyHub

**专为 AI Agent、指纹隔离浏览器与多账号矩阵打造的智能代理分发枢纽**

[![GitHub Release](https://img.shields.io/github/v/release/ningnuo-dot/AgentProxyHub?style=flat-square&color=blue)](https://github.com/ningnuo-dot/AgentProxyHub/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-slate.svg?style=flat-square)](README.md)
[![MCP Ready](https://img.shields.io/badge/Protocol-Model%20Context%20Protocol%20(MCP)-purple.svg?style=flat-square)](mcp/server.py)

[中文说明](README.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)

</div>

---

### 💡 为什么需要 AgentProxyHub？

在做海外多账号矩阵、指纹浏览器多开（P1 / CloakMulti / AdsPower）或运行 Claude Code / 自动化爬虫时，常规代理软件通常存在以下痛点：

1. **单出口与风控串联**：普通梯子通常只开放一个本地混合端口（如 `7890`），多个账号共用同一出口，极易因 IP 撞车导致批量封号。
2. **AI 与社媒风控黑盒**：很多节点虽然能打开网页，但访问 Anthropic 报 Cloudflare 1020 阻断、访问 Google 被判定“送中”（Google Country: China）、注册 Facebook 遇到机房 IP 秒死，人工逐个测试极为繁琐。
3. **Agent 无法程序化调度**：AI 编程助手（如 Cursor、Claude Desktop、自定义 Agent）无法感知当前哪个端口可用、哪个节点能跑 Claude、更无法帮特定的自动化环境固定 IP。

**AgentProxyHub** 将上游订阅（Clash/Mihomo）自动映射为本地连续的独立端口池（SOCKS5 `20001+` / HTTP `30001+`），配合**规则驱动的多场景测试雷达（Scene Matrix）**与 **标准 MCP 协议服务**，让人类与 AI 智能体都能随取随用。

---

### ✨ 核心特性

- 🔌 **一节点一独立端口**：单订阅自动生成 80~120+ 独立本地端口池（双轨支持 SOCKS5 与 HTTP CONNECT），专供指纹浏览器做环境物理隔离。
- 🎯 **多场景靶场与智能评判（Scene Matrix）**：
  - **✨ 反重力 / Gemini**：Google 官方区域认证，彻底剔除“送中”节点；
  - **🟣 Claude 专属**：直连 `api.anthropic.com`，防 Cloudflare 1020/403 封锁；
  - **🟢 ChatGPT / OpenAI**：API 高速通道实测，支持 SSE 流式稳定传输；
  - **🔵 Facebook / 海外社媒**：严格限定真实住宅/家宽 IP，剔除机房出口与重复 IP，保障养号粘性。
- 🧩 **后人可随意扩展（`scenes.json` 驱动）**：界面与规则完全解耦，新增 TikTok、Twitter 或其他小众业务规则，只需在 JSON 追加几行，面板与 Agent 自动识别。
- 🤖 **原生 MCP 服务（Model Context Protocol）**：暴露 `list_matched_proxies`、`bind_profile_proxy` 等标准工具，允许 Agent 在会话中自主查询、测绘、并把端口打入指定软件。
- 📱 **手机/局域网免装 App 分流总线**：内置局域网智能网关（如 `192.168.0.107:39999`），手机或内网设备无需安装客户端，直连电脑即刻享受分流。
- 🎨 **Win11 暗黑极简控制面板**：原生 WPF 架构，托盘常驻，随取随用，毫秒级响应。

---

### 📦 绿色发行版直接下载（小白推荐 · 免配环境）

> **你不需要配置任何复杂的开发环境！我们已经为你编译并打包好了绿色完整发行版。**

1. 前往右侧 **[Releases 发行页](https://github.com/ningnuo-dot/AgentProxyHub/releases)**；
2. 下载 `AgentProxyHub-v1.0.0-windows-x64.zip`；
3. 解压到任意目录（例如 `D:\AgentProxyHub`）；
4. 双击运行 **`启动AgentProxyHub.bat`** 即可直接弹出控制面板！

---

### 🚀 快速上手与使用

#### 1. 导入你的机场订阅
打开 `config/config.yaml`（可从 `config/config.example.yaml` 复制），填入你的订阅链接：
```yaml
upstream:
  subscriptions:
    - name: "MyAirport"
      url: "https://your-airport.com/api/v1/client/subscribe?token=xxx"
      enabled: true
```
或者双击运行 `打开面板.bat`，在界面中直接取用已生成的节点列表。

#### 2. 在指纹浏览器中使用
- **SOCKS5 格式**：`127.0.0.1:20001`（节点 1）、`127.0.0.1:20002`（节点 2）...
- **HTTP 格式**：`127.0.0.1:30001`（节点 1）、`127.0.0.1:30002`（节点 2）...
- 面板支持一键复制 FlowTools 推荐格式、SOCKS5 批量清单与 P1 智能解析格式。

#### 3. 接入 Claude Desktop / Cursor / AI Agent
在你的 `claude_desktop_config.json` 中加入以下配置：
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
配置完成后，直接在对话框中告诉 AI：
> *“帮我找一个延迟最低的美国住宅节点，并绑定到我的推特环境1中。”*  
AI 将自动调用 MCP 完成筛选、测试并锁定绑定。

---

### 🛠️ 社区共建与规则扩展

本项目设计之初即追求**极简内核与完全外置的规则引擎**。欢迎提交 Pull Request：

1. **添加新场景规则**：在 `config/scenes.json` 中提交新的业务探针定义（如 TikTok 严选、跨境电商住宅规则）。
2. **贡献软件注入适配器（Injectors）**：在 `core/` 下提交针对 AdsPower、Hubstudio、BitBrowser 等指纹软件的自动配置写入脚本。

---

### 📄 开源许可证
本项目采用 [MIT 许可证](LICENSE)。
