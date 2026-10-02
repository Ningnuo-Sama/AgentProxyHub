# AgentProxyHub 全网互联拓扑、全量接口与生态流动技术白皮书 (全生态扩展版)

> **文档性质**：本文档为 AgentProxyHub 系统及其**全网互联生态（Visual Pro、Flow-Tools、Daedalus 无限画布、CloakMulti、手机分身真机、鲸管家、Hermes、Antigravity）**的权威全貌技术白皮书。配套高保真 H5 动态流动大屏位于 `docs/agentproxyhub-panoramic-flow.html`。

---

## 目录
1. [系统全局定位与全网互联背景](#一系统全局定位与全网互联背景)
2. [底层出口端口池分布与硬约束](#二底层出口端口池分布与硬约束)
3. [八大战术战区分层全息总览](#三八大战术战区分层全息总览)
4. [【核心关联】Ariadne Visual Pro (8320) 的代理策略与防污染直连](#四核心关联ariadne-visual-pro-8320-的代理策略与防污染直连)
5. [【核心关联】Flow-Tools (8001) 的 7 Google 号池与欺骗网关](#五核心关联flow-tools-8001-的-7-google-号池与欺骗网关)
6. [【核心关联】Daedalus 无限画布 (3000) 与 Canvas Agent (17371)](#六核心关联daedalus-无限画布-3000-与-canvas-agent-17371)
7. [【核心关联】CloakMulti (7800) 的端口锁定账本共写机制](#七核心关联cloakmulti-7800-的端口锁定账本共写机制)
8. [【核心关联】手机分身 Root 真机 UID 级物理隔离与微信创作闭环](#八核心关联手机分身-root-真机-uid-级物理隔离与微信创作闭环)
9. [【核心关联】鲸管家 (8766) 与 Hermes 微信直推向主人摇人](#九核心关联鲸管家-8766-与-hermes-微信直推向主人摇人)
10. [MCP 26 大工具服务全量雷达字典](#十mcp-26-大工具服务全量雷达字典)
11. [功能节点实施状态对照表 (铁律规范)](#十一功能节点实施状态对照表-铁律规范)
12. [配套 H5 动态流动大屏与增量跟进契约](#十二配套-h5-动态流动大屏与增量跟进契约)

---

## 一、系统全局定位与全网互联背景

随着本地自研工具链（Ariadne Visual Pro、Flow-Tools、Daedalus 无限画布、手机分身、鲸管家）的快速膨胀，各软件若各自配置海外代理，会导致**单端口撞车被封、DNS 假 IP 污染、反代循环死锁、密钥明文泄露**等毁灭性问题。

**AgentProxyHub** 扮演整套私有基础设施的**物理出口枢纽与安全路由器**：
1. **统一出口池**：提供 125 个独立出口（蜂窝 21001-21080 / 星辰 22001-22045 / 局域网 39999），为每个 Google 账号与指纹浏览器分配专属 IP。
2. **强制 0ms 回环**：全系统注入 `NO_PROXY`，禁止本地私有反代（8045、8001、8320、3000、8766）走海外代理。
3. **防假 IP 污染与直连支持**：协同 Visual Pro 实现阿里 DoH 穿透，避开 TUN fake-ip 198.18 导致的 TLS 握手崩溃。
4. **全自动无感凭据治理**：Windows DPAPI 硬件加密管理所有 API Key 与 Token，绝不落地明文。

---

## 二、底层出口端口池分布与硬约束

| 端口号段 | 协议 | 节点归属 | 节点规模 | 业务承载与硬约束 |
| :--- | :---: | :--- | :---: | :--- |
| **`21001 - 21080`** | SOCKS5 | 蜂窝 (FengWo) | 80 个 | **Antigravity 7 账号 & Flow-Tools 号池强粘性锚定段**。严禁变更段位！ |
| **`31001 - 31080`** | HTTP CONNECT | 蜂窝 (FengWo) | 80 个 | 配套 HTTP 协议通道，供仅支持 HTTP 代理的爬虫或工具使用。 |
| **`22001 - 22045`** | SOCKS5 | 星辰 (XingChen) | 45 个 | 高质量住宅/家宽备用池，22002 (US)、22004 (JP) 已锁定环境。 |
| **`192.168.0.107:39999`** | Mixed (自适应) | 局域网总线 | 1 个 | 供实体 Root 手机（小米8 Lite `51e0d4aa`）免装梯子 App 直接分流。 |
| **`127.0.0.1:8045/8001/8320`** | HTTP | 本地私有反代 | 3 个 | **强制 `NO_PROXY` 0ms 物理回环**，严禁套海外代理！ |

---

## 三、八大战术战区分层全息总览

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                       AGENTPROXYHUB 全网互联生态流动拓扑 (八大战区)                         │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
  ZONE 1: 上游订阅与凭据投喂金库 ──(紫光凭据)──► ZONE 2: 端口池内核与双看门狗自愈 (125出口)
  ├── 凭据无感投喂 (8大类自动归档)             ├── Mihomo 核心 (PID: 56072, 125出口)
  ├── DPAPI 本地硬件级加密                     ├── cert-watchdog (证书漂移 0秒热重载)
  ├── 蜂窝/星辰订阅拉取与流量侦测             ├── pool-guard (Google 送中同区换绑)
  └── 火山 TOS 预签名垫图中继 【未实现】       └── 39999 局域网免梯分流总线
                                                          │
                                                          ▼ (绿光探测)
                                            ZONE 3: 探测矩阵与置信度引擎
                                            ├── 多场景靶场雷达 (scenes.json)
                                            ├── Google 真实自判探针 (China一票否决)
                                            └── 40%/30%/30% 加权打分与 72h 观察钟
                                                          │
                                                          ▼ (金光 MCP)
                                            ZONE 4: MCP 26 大工具服务矩阵
                                            ├── 调度绑定类 (6 工具)
                                            ├── 探针审计类 (4 工具)
                                            ├── 上游管理类 (3 工具)
                                            ├── 自治运维类 (5 工具)
                                            └── 凭据策略类 (6 工具)
                                                          │
       ┌──────────────────────────────────────────────────┴──────────────────────────────────────────────────┐
       ▼ (青光数据/反代流)                                                                                   ▼ (青光出口分流)
  ZONE 5: 模型与媒体反代网关层                                              ZONE 6: 用户应用与创作消费层
  ├── Ariadne Visual Pro (8320 防污染直连)                                  ├── Daedalus 无限画布 (3000 前端交互)
  ├── Flow-Tools (8001 7谷歌号池网关)                                       ├── Canvas Agent 桥 (17371 外部编排)
  ├── Antigravity Tools (8045 LLM 反代网关)                                 └── CloakMulti (7800 指纹浏览器控制台)
  └── 统一大模型 API 网关 (32000 盲中转) 【待开发】
       │                                                                                                     ▲
       │ (微信出图指令)                                                                                      │ (锁定账本共写)
       ▼                                                                                                     │
  ZONE 7: 手机分身真机硬件与创作闭环 ────────────────────────────────────────────────────────────────────────┘
  ├── 小米8 Root 真机 (51e0d4aa)
  ├── iptables UID 硬件级网络重定向 (分流至 21001/21003/21005/21008)
  ├── USB 硬件反向穿透总线 (adb reverse 48921, <20ms Webhook)
  ├── 双轨数据保活 (WCDB 直读 EnMicroMsg.db 破除微信折叠)
  └── 微信端到端聊天生图 (CreationBridge: /生图 ➔ 调 8001/8320 ➔ 勾选原图回发)
       │
       ▼ (碰面/借钱高危触发)
  ZONE 8: 桌面管家与终极向主人摇人闭环 (100% 拦截)
  ├── 鲸管家 8766 通讯与双向运维网关 (DPAPI 自动鉴权, 容量 2048 去重)
  ├── Live2D 桌宠置顶穿透窗口 (6表情+3动作+自主闲时情绪算法)
  ├── 孤儿进程治理与白名单防护 (探查 Win32_Process, 防误杀系统服务)
  ├── Hermes Agent 微信 Bot (腾讯 iLink 官方协议, NO_PROXY 直连)
  └── 终极安全熔断向主人摇人 (100% 阻断自动化 ➔ 托盘标红 ➔ 桌宠冒泡 ➔ Hermes 直推一帆)
```

---

## 四、【核心关联】Ariadne Visual Pro (8320) 的代理策略与防污染直连

### 4.1 服务架构与定位
* **代码入口**：`D:\GitHub\ariadne\tools\ariadne-visual-pro\src\scene_service.py`
* **物理监听**：`127.0.0.1:8320`（标准库多线程 HTTP 服务）
* **核心职责**：女装商品视觉摆拍、服装提取、四视图生成、Midjourney 官方管道、AICost/Seedance 视频生成。

### 4.2 为什么必须“强行绕过代理”？（核心黑科技）
源码审查显示，Visual Pro 内部针对外部海外 AI 服务，**显式实现了强制直连（NO_PROXY）与防假 IP 污染直连**：
1. **Kie 与 Midjourney 强行直连 (`ProxyHandler({})`)**：
   * 代码在 `kie_generation.py` 与 `mj_service.py` 中强制构造：
     ```python
     _direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
     ```
   * **实测根因**：本机系统代理或透明代理会劫持修改 HTTP 请求头，导致 Kie 鉴权报错；同时 TTAPI 部署在 Cloudflare 后面，走常规梯子节点容易触发 1020 盾，因此必须走纯净直连 + 定制 UA。
2. **阿里 DoH 解析真实 IP + PinnedHTTPSConnection (避开假 IP 污染)**：
   * 在 `neuxs_generation.py` 中，本地代理的 TUN fake-ip 机制常将海外 CDN 解析为 `198.18.0.0/15`，经由代理转发极易发生 `SSL UNEXPECTED_EOF`；
   * 代码通过 `https://223.5.5.5/resolve?name={host}&type=A`（阿里 DoH 直连）查询域名真实物理 A 记录；
   * 建立 `PinnedHTTPSConnection`：**TCP 层直连真实物理 IP，TLS 握手层保留原域名 SNI**，彻底绕过代理劫持！
3. **与 AgentProxyHub 的协作**：
   * Visual Pro 的 `/deep-optimize`（提示词深度多模态增强）并不直连外网，而是向 `127.0.0.1:8045`（Antigravity）或 `127.0.0.1:8001`（Flow-Tools）索取免费的 Gemini 算力，走的是 **0ms 本地回环**。

---

## 五、【核心关联】Flow-Tools (8001) 的 7 Google 号池与欺骗网关

### 5.1 服务架构与定位
* **代码入口**：`D:\GitHub\Flow-Tools\src-tauri\src\gateway.rs`
* **物理监听**：`127.0.0.1:8001`（Rust 高性能原生网关）
* **核心职责**：管理 7 个 Google Labs 账号池（Imagen 3、VideoFX、Veo），提供 0 成本、高保真的生图与视频服务。

### 5.2 账号粘性绑定与漂移熔断
* **凭据安全**：账号密码与 Token 存储于 `%LOCALAPPDATA%\FlowTools\accounts.json`，采用 Windows `CryptProtectData`（DPAPI）加密保护，绝无明文落盘。
* **锁定蜂窝端口**：每个 Google 账号与 AgentProxyHub 蜂窝端口 1:1 固化：
  * 例如账号 `393usdb@gmail.com` 固化绑定 `socks5h://127.0.0.1:21013`（必须用 `socks5h` 强制远端 DNS 解析）；
  * 同时锁定 `pinned_exit_ip`（如 `140.235.142.76`，盐湖城固定出口）。
* **同区自愈 vs 跨国熔断**：网关在每次请求前探活出口；若在同机房同国轮换，自动更新 `pinned_exit_ip`；若发生跨国漂移，立即熔断停机，防止 Google 账号被封。

### 5.3 Ariadne 协议欺骗外壳 (零成本接入画布)
* Flow-Tools 实现了 `ARIADNE_GATEWAY_ADAPTER_SPEC.md` 规范，在 `8001` 上拦截并实现了 `/v1beta/models/*` 与 `/upload/v1beta/files` 伪装端点；
* Daedalus 画布与手机分身无需任何代码修改，只需将 Base URL 指向 `http://127.0.0.1:8001`，即可免费白嫖 Imagen 3 和 Veo 出图能力，产物以本地文件 `http://127.0.0.1:8001/local_assets/...` 秒级返回。

---

## 六、【核心关联】Daedalus 无限画布 (3000) 与 Canvas Agent (17371)

### 6.1 服务架构与伴生服务群
由 `启动无限画布.bat` 统一拉起四大伴生服务：
1. `127.0.0.1:3000`：前端交互画布（Vite + React）；
2. `127.0.0.1:8320`：Visual Pro 场景引擎与摆拍服务；
3. `127.0.0.1:17371`：Canvas Agent 桥（`infinite-canvas` MCP 服务端，实现 AI 编排白板）；
4. `127.0.0.1:8001`：Flow-Tools 免费号池生图网关。

### 6.2 协同调用链路
* **密钥与设置收口**：画布侧栏的 `canvas-ariadne-settings-tab.tsx` 直接通过 HTTP 读写 `http://127.0.0.1:8320/settings`，实现跨浏览器共享密钥；
* **0 成本生图节点**：画布中的 Google Omni 节点把请求发送给 Flow-Tools (8001)，产物直接落地到 `D:\AI视频\无限画布`，并在画布上实时呈现图元；
* **Agent 自动化驱动**：外部 AI（Claude Code / DSH）通过 `infinite-canvas` MCP 连接 `17371` 端口，自动在画布上规划节点拓扑、调整视口与触发批量生图。

---

## 七、【核心关联】CloakMulti (7800) 的端口锁定账本共写机制

### 7.1 服务架构与定位
* **代码入口**：`D:\GitHub\CloakMulti\cloakmulti\aphub.py`
* **物理监听**：`127.0.0.1:7800`（Web 指纹浏览器控制台）
* **核心职责**：管理几十个独立的指纹浏览器环境（Profile），为 Twitter、Facebook、Google 养号提供物理级环境隔离。

### 7.2 跨进程持锁共写 `bindings.json`
* **测绘数据消费**：CloakMulti 启动时读取 `D:\GitHub\AgentProxyHub\data\nodes.json`，按 `{"S": 4, "A": 3, "B": 2, "C": 1}` 筛选 S/A/B 级空闲端口；
* **共写排他锁契约**：
  * **CloakMulti 侧**：写入时先写 `.tmp` 临时文件，再通过 `os.replace` 原子替换；
  * **AgentProxyHub MCP 侧**：使用 Windows `msvcrt.locking(..., msvcrt.LK_LOCK, 1)` 对 `data/bindings.lock` 施加底层排他锁；
  * **严禁抢占**：若指定端口已被其他 Profile 占用，强行抛出拒绝并返回占用者名称，严格保证环境与出口端口的 **1:1 绝对排他性**。

---

## 八、【核心关联】手机分身 Root 真机 UID 级物理隔离与微信创作闭环

### 8.1 硬件级 UID 网络重定向（一部手机多住宅出口）
* **实体机**：小米8 青春版（`51e0d4aa`，MIUI 12.5，Magisk Root）；
* **内核重定向**：手机内运行多用户分身（User 0、User 11、User 12、User 13），分别对应小红书、微信等矩阵号；
* **iptables 规则**：按应用 UID 拦截 TCP 流量，重定向到手机内端口 `10801~10804`；
* **物理映射**：手机端代理将 4 个端口分别转发至宿主机 AgentProxyHub 的 `21001`、`21003`、`21005`、`21008`，分别出口至香港数码通、台湾等不同真实住宅 IP，实现**真机多账号完全物理隔离**。

### 8.2 USB 硬件反向穿透与 WCDB 破除通知折叠
* **物理隧道**：守护进程维持 `adb reverse tcp:48921 tcp:48921`，SmsForwarder 收到消息在 <20ms 内推入 PC 端 SQLite 收件箱；
* **直读 WCDB**：以 Root 权限直接读取 `EnMicroMsg.db`，彻底解决微信多条消息折叠为“[3条] 微信消息”导致 OCR 漏判的痛点；结合 Scrcpy 0.56ms 视频流按需唤醒屏幕。

### 8.3 微信端到端聊天生图与原图回发 (CreationBridge)
* 微信好友向分身发送「/生图 + 描述」➔ 手机分身识别意图并追问横竖屏；
* 异步调度 Flow-Tools (8001 免费 Imagen 3) 或 Ariadne (8320 MJ 付费管道) 出图；
* 图片生成后自动 `adb push` 到手机相册，UI 自动化仿生点击勾选「原图」发送回给好友，完成移动创作闭环。

---

## 九、【核心关联】鲸管家 (8766) 与 Hermes 微信直推向主人摇人

### 9.1 鲸管家 8766 桌面信使与主机安全保洁员
* **双向网关**：原生 `node:http` 监听 `127.0.0.1:8766`，启动时通过 `resolve_notify_token.py` 自动从 DPAPI 金库提取鉴权 Token；
* **气泡与状态机**：`POST /notify` 驱动 Live2D 桌宠的 6 大表情（`happy`、`sleepy`、`angry`、`work`、`wave`、`wronged`）与 3 组动作；
* **系统运维 RPC**：`POST /task` 支持外部系统调度 `scan_orphans`、`clean_safe_orphans`、`whitelist_add`，实时查杀无主僵尸进程；
* **硬白名单保护**：加白保护 `AgentProxyHub`、`mihomo.exe`、`Hermes`、`Flow-Tools`，严禁误杀系统服务。

### 9.2 终极安全熔断与向主人摇人闭环 (100% 拦截)
* **敏感词红线**：一旦会话涉及线下碰面、签署合同、转账借钱等高危行为；
* **100% 阻断自动化**：立刻截断回复并标记 `need_takeover`；
* **多路向主人摇人**：
  1. 手机分身本地托盘图标强行标红；
  2. 鲸管家 8766 桌宠弹出委屈表情气泡；
  3. Hermes Agent 通过腾讯 iLink 微信官方协议，直接向一帆本人手机微信发送报警通知，等待真人最终裁决。

---

## 十、MCP 26 大工具服务全量雷达字典

服务入口：`python D:\GitHub\AgentProxyHub\mcp\server.py`，采用标准 JSON-RPC 2.0 stdio 协议。

### 10.1 节点调度与绑定类 (6)
1. **`agent_recommend_proxy`**：以 Google 自判国和置信度推荐最优节点，只读，绝不擅自换绑。
2. **`list_matched_proxies`**：按场景靶场（claude/openai/gemini/fb）筛选 S/A 级出口。
3. **`get_proxy_command`**：一键生成 PowerShell/Bash/Chrome/Claude Code 挂载指令。
4. **`bind_profile_proxy`**：锁定指纹环境与专属端口的 1:1 映射（持 bindings.lock）。
5. **`get_profile_bindings`**：读取环境锁定账本与 Antigravity 7 账号粘性锚定。
6. **`auto_rebind_profile`**：仅当绑定端口彻底死线时在同大区内安全换绑。

### 10.2 探测与国家自判类 (4)
7. **`google_verify_proxy`**：解析 Google 真实 Country Version，识破伪装海外的“送中”节点。
8. **`test_proxy_target`**：现场通过指定端口探测目标 URL 的真实连通性与握手延迟。
9. **`audit_confidence`**：审计节点时序置信度（40%稳定性/30%合规/30%健康）与漂移史。
10. **`list_scenes`**：列出系统当前配置的所有场景靶场规则（外置 scenes.json 驱动）。

### 10.3 上游机场管理类 (3)
11. **`get_upstream_sources`**：读取所有已登记机场与订阅源配置，Token 默认脱敏遮蔽。
12. **`set_upstream_credential`**：登记或更新机场凭据（API Token、订阅直链或 Profile 路径）。
13. **`refresh_upstream_nodes`**：拉取已登记上游并原子更新节点快照；失败保留上一份有效快照。

### 10.4 自治中枢与驻场运维类 (5)
14. **`autonomy_status`**：读取只读自治状态快照；不凭快照虚报存活。
15. **`autonomy_action`**：管理自治开关、清理 7 天事件；不改端口绑定、不启动外部付费任务。
16. **`resident_engineer`**：驻场工程师离线体检、状态读取与报告模板生成；零付费模型调用。
17. **`kernel_recovery`**：检测并自愈恢复已退出的本地代理内核，平滑重启保障业务连续性。
18. **`jingguanjia_orphan`**：巡检本地孤儿进程与残留句柄并提供自愈建议。

### 10.5 凭据安全与路由类 (6)
19. **`vault_status`**：查看 Windows DPAPI 本地凭据金库条目总数与元数据。
20. **`proxy_network_route`**：给出 direct/proxy 建议；**强制本地反代 0ms 物理回环**。
21. **`pricing_quote`**：按供应商与模型查询人民币参考报价；无核验规则返回待核价。
22. **`channel_health`**：检查 Gemini、Flow-Tools、OpenViking、鲸管家等连通状态。
23. **`cliproxyapi_health`**：专向探测本地 8045 CLIProxyAPI 网关健康与模型池。
24. **`notify_jingguanjia`**：联动本地 8766 鲸管家桌宠发送结果气泡动画；严禁发送凭据。
25. **`model_policy`**：读取本地模型调用约束（思考 Token 预算与降级准则）。
26. **`usage_log`**：读取脱敏后的模型调用消耗记账统计（Token、耗时、预估成本）。

---

## 十一、功能节点实施状态对照表 (铁律规范)

| 模块名称 | 所在路径 | 当前状态 | 实施依据与现状说明 |
| :--- | :--- | :---: | :--- |
| **凭据无感投喂与分类引擎** | `core/resident_engineer.py` | `【已实现】` | 正则识别 8 大类，DPAPI 自动入库，零手动维护。 |
| **DPAPI 硬件级加密凭据金库** | `core/credential_vault.py` | `【已实现】` | Windows 本地加密，零明文外泄，双轨隔离。 |
| **上游机场订阅拉取引擎** | `core/upstream_fetcher.py` | `【已实现】` | 蜂窝/星辰多源抓取，持久化于 upstreams.json，原子双写锁。 |
| **Mihomo 独立端口池内核** | `core/gen-config.ps1` | `【已实现】` | 映射 125 端口 (21001-22045)，PID 56072 稳定运行。 |
| **证书漂移看门狗** | `scripts/cert-watchdog.ps1` | `【已实现】` | 探测 SNI 失败自动注入 skip-cert-verify 并 9090 API 0秒热重载。 |
| **Google送中一票否决号池守护** | `scripts/pool-guard.ps1` | `【已实现】` | 实测 terms 发现送中，同区最小漂移替补，守护 7 谷歌账号。 |
| **局域网免装 App 分流总线** | `config/config.yaml` | `【已实现】` | 192.168.0.107:39999，供手机分身 Root 机直连。 |
| **多场景规则靶场雷达** | `config/scenes.json` | `【已实现】` | 覆盖 Antigravity、Claude、OpenAI、FB、General 5 大场景。 |
| **Google 官方自判国家探针** | `core/probe_engine.py` | `【已实现】` | 实测解析 Country Version，识破“送中”节点。 |
| **三维加权时序置信度引擎** | `core/confidence_engine.py` | `【已实现】` | 40%/30%/30% 加权打分，72h 观察钟与洲际一票否决。 |
| **MCP 26 大工具服务矩阵** | `mcp/server.py` | `【已实现】` | 完整 26 工具实现，文件锁保护，已接入 DSH/Cursor。 |
| **Ariadne Visual Pro (8320)** | `D:\GitHub\ariadne` | `【已实现】` | 视觉制作中枢，集成 ProxyHandler({}) 强直连与阿里 DoH 穿透。 |
| **Flow-Tools 网关 (8001)** | `D:\GitHub\Flow-Tools` | `【已实现】` | 7个 Google 号池调度器，DPAPI 加密，Ariadne 协议欺骗外壳。 |
| **Antigravity Tools (8045)** | `C:\Users\1\.antigravity_tools` | `【已实现】` | Gemini/Claude 多模型本地反代网关，7 个账号粘性锚定池。 |
| **Daedalus 无限画布 (3000)** | `D:\GitHub\daedalus-canvas` | `【已实现】` | 前端无限画布主系统，侧栏直连 8320 密钥，插件直连 8001 免费出图。 |
| **Canvas Agent 外部编排桥** | `canvas-agent\` (17371) | `【已实现】` | infinite-canvas MCP 服务端，支持外部 AI 自动编排画布。 |
| **CloakMulti 指纹浏览器控制台**| `D:\GitHub\CloakMulti` (7800) | `【已实现】` | 多环境指纹浏览器调度，与 APH 跨进程共写 data/bindings.json。 |
| **手机分身小米8真机UID隔离** | `D:\GitHub\手机分身` | `【已实现】` | 多用户分身通过 iptables UID 分流至 21001/21003/21005/21008。 |
| **USB 硬件反向穿透总线** | `D:\GitHub\手机分身` (48921)| `【已实现】` | adb reverse tcp:48921 tcp:48921，<20ms 推入 SQLite 收件箱。 |
| **双轨数据保活 (WCDB直读)** | `D:\GitHub\手机分身` | `【已实现】` | Root 直读 EnMicroMsg.db 破除微信折叠，Scrcpy 视频流按需唤醒。 |
| **微信端到端生图与原图回发** | `D:\GitHub\手机分身` | `【已实现】` | 聊天发 /生图 ➔ 询问横竖屏 ➔ 调 8001/8320 ➔ 勾选原图回发。 |
| **终极安全熔断向主人摇人** | `D:\GitHub\手机分身` | `【已实现】` | 碰面/借钱资金 100% 熔断 ➔ 托盘标红 ➔ 桌宠冒泡 ➔ Hermes 直推。 |
| **鲸管家 8766 通讯与运维网关**| `D:\GitHub\鲸管家` | `【已实现】` | node:http POST /notify & 双向 RPC POST /task，容量 2048 去重。 |
| **Live2D 桌宠置顶穿透窗口** | `D:\GitHub\鲸管家` | `【已实现】` | screen-saver 置顶穿透，6 表情 + 3 动作 + 自主闲时情绪算法。 |
| **孤儿进程治理与白名单防护** | `D:\GitHub\鲸管家` | `【已实现】` | 遍历 Win32_Process，硬加白保护系统服务，清理僵尸进程。 |
| **Hermes Agent 微信 Bot** | `D:\Program Files (x86)\hermes` | `【已实现】` | 腾讯 iLink 微信官方通道 (NO_PROXY 直连)，挂载 APH MCP。 |
| **统一大模型 API 网关 (32000)** | `core/api_gateway.py` | `【待开发】` | 本地轻量反代服务，虚拟 Token 盲中转与防偷 Key 静默切线。 |
| **火山引擎 TOS 垫图图床中继** | `core/tos_relay.py` | `【未实现】` | 解决 Midjourney TTAPI 垫图与视频首尾帧上传问题。 |
| **跨物理机多活边缘网关集群** | `core/cluster/` | `【展望中】` | 多台机器间节点池状态同步与全局负载均衡。 |

---

## 十二、配套 H5 动态流动大屏与增量跟进契约

### 12.1 流动大屏核心能力
打开入口：双击运行根目录下的 `打开全貌流动图.bat` 或在浏览器中访问 `docs/agentproxyhub-panoramic-flow.html`。
* **高精度 Canvas 动态流动光斑**：数据粒子沿真实的贝塞尔曲线管线高速奔涌，青蓝（代理）、翠绿（健康）、琥珀金（MCP）、霓虹红（告警）、赛博紫（凭据）色彩区分。
* **全网穿透聚焦**：单击任何节点（如点击 `Ariadne Visual Pro` 或 `Flow-Tools`），所有与它直接连接的上下游全部高亮发光，无关节点自动暗淡，侧边抽屉滑出完整代码入口与业务契约。
* **自由平移缩放**：按住鼠标拖拽平移画布，滚轮缩放，点击顶栏“🎯 居中复位”即可自适应屏幕。
* **实施状态过滤**：点击【已实现】/【待开发】/【未实现】/【展望中】药丸标签，一键过滤高亮对应周期的功能。

### 12.2 后续增量跟进维护机制 (面向后续扩展)
* 整个 H5 页面采用**解耦的数据驱动架构**，所有节点坐标、连线拓扑、代码路径均收敛在 `agentproxyhub-panoramic-flow.html` 内部的 `GRAPH_DATA` 常量中。
* **跟进契约**：后续系统新增任何新接口、新上游、新模块或状态演进时，您只需向 Agent 提出需求，Agent 直接在 `GRAPH_DATA` 中追加对应节点与连线，页面拓扑和流动管道便会**自动连通并动态流动**，无需重构任何前端页面！
