# 出海代理中枢与号池全自愈生态：全盘架构设计任务书与落地交付总纲 (完整全量版)

> **文档代号**: RFC-MASTER-20261001-ARCHITECTURE-DIRECTIVE-FULL  
> **编写主体**: 本地工程代理组（Codex / 本地落地执行管家）  
> **接收对象**: GPT 架构师 / 全局系统设计中枢  
> **归档位置**: `D:\GitHub\AgentProxyHub\docs\ARCHITECTURE_DIRECTIVE_FOR_GPT_20261001.md`  
> **核心原则**: **“主动权在手，事实已锁死，前稳后活。GPT 专心细化出具架构任务书与契约，本地工程秒级落地并 Push”**

---

## 一、 顶层业务目标与用户“零心智负担”契约

1. **彻底终结繁琐的人工运维**：用户日常唯一需要做的，就是在 CloakMulti 中登录 Google 账号。其余所有**凭据提取、端口映射、节点失效自愈、坏线刷新、跨区防封锁、物理设备微信通知**全部交由系统后台自动运转。
2. **免打扰承诺**：只要微信没响警报，用户完全不用管；一旦微信响了或桌宠弹大字气泡，说明触发了不可逆致命异常（全区断流、Token 彻底失效、Google 人机跳脸），且已带有白话根因与 1 分钟排障指引。

---

## 二、 涉案 6 大系统物理资产与现场实测现状全景

| 序号 | 目标系统 / 仓库 | 物理位置与网关端口 | 真实状态与未落地积压资产 |
| :--- | :--- | :--- | :--- |
| **1** | **AgentProxyHub**<br>(代理中枢与唯一真理账本) | 源码: `D:\GitHub\AgentProxyHub`<br>正式运行: `D:\Program Files\AgentProxyHub`<br>Mihomo 内核控制器: `127.0.0.1:21909` | **已完成**：MCP 服务端新增 `set_upstream_credential` 与 `get_upstream_sources`，7 项 E2E 绿灯通过；捕获两家全量 Web Token；置信度评分引擎就绪。<br>**待落地**：接入虚拟端口策略组（Virtual Port Router），彻底脱离对客户端的依赖。 |
| **2** | **Antigravity Tools**<br>(大模型对话与反代网关) | 源码: `D:\GitHub\Antigravity-Manager`<br>运行: `D:\Program Files\Antigravity Tools`<br>网关端口: `127.0.0.1:8045`<br>配置: `C:\Users\1\.antigravity_tools\gui_config.json` | **现状**：6 个活跃 Google 账号被人工硬编码钉死在 26 个杂乱历史端口中（40KB 膨胀 JSON）；<br>**待落地**：执行“前稳后活”大一统收口，账号死锁保留，端口对齐新设计标准。 |
| **3** | **Flow-Tools**<br>(Google Labs 媒体号池与网关) | 源码: `D:\GitHub\Flow-Tools`<br>网关端口: `127.0.0.1:8001` | **现状**：已实装 ImageFX/VideoFX/Veo 全参数提取与 Ariadne 原生伪装路由；<br>**待落地**：Rust 端读写解耦，合并不死锁的 `reliability_contract.rs` 与 `bin_sync.rs`。 |
| **4** | **CloakMulti**<br>(指纹隔离与账号录入前台) | 源码: `D:\GitHub\CloakMulti`<br>控制台: `127.0.0.1:7800` | **现状**：Flow-Tools 准入机制 `flow_admission.py` 已写好；<br>**待落地**：合并不阻塞调试解挂守护（`unpause_daemon.py`），通过 CDP 提取凭据直传下游。 |
| **5** | **鲸管家**<br>(Live2D 桌面宠物与第一信使) | 源码: `D:\GitHub\鲸管家`<br>常驻进程: PID 4384 (electron) | **现状**：2K PSD 修复与表情状态机就绪；内置孤儿清理（`orphan-cleaner`）；<br>**待落地**：将 `agentproxyhub` 录入防误杀白名单，主进程暴露 `127.0.0.1:8766/notify` 告警端点。 |
| **6** | **Root 手机分身**<br>(小米 8 Lite 物理告警兜底) | 源码: `D:\GitHub\手机分身`<br>物理通道: USB 反向穿透 `127.0.0.1:48921` | **现状**：已完成 Gemini 3.8 Flash 双脑跑分（`benchmark_dual_brain_results_38flash.json`）；<br>**待落地**：常驻微信失焦广播自拉起与致命异常 Webhook 接收。 |

---

## 三、 本地已引用并确认的关键规则与历史文件索引

在编制本任务书前，本地工程已调取并对齐以下全部核心资产与工作区规则：
1. **工作区协作总规则**：`D:\GitHub\AGENTS.md`（优先级判断、零脏区污染、代码最小变更原则）；
2. **多 Agent 协同与自动推进全景**：`D:\GitHub\AgentProxyHub\docs\AUTONOMOUS_PROXY_INTEGRATION_SPEC.md`；
3. **上游机场 Token 逆向与 MCP 侦查报告**：`D:\GitHub\AgentProxyHub\docs\UPSTREAM_AIRPORT_TOKEN_RECON_REPORT_20261001.md`；
4. **Antigravity 账号收口提案**：`D:\GitHub\AgentProxyHub\docs\PROPOSAL_ANTIGRAVITY_PORT_MIGRATION_20261001.md`；
5. **智谱 GLM 本地中枢与决策引擎规范**：`D:\GitHub\GLM-4flash\README.md` 与 `core/judge.py`；
6. **鲸管家孤儿进程防御规则**：`D:\GitHub\鲸管家\src\features\orphan-cleaner\core\rules.ts`；
7. **Flow-Tools 稳定性契约**：`D:\GitHub\Flow-Tools\src-tauri\src\reliability_contract.rs`；
8. **CloakMulti CDP 流转设计**：`D:\GitHub\CloakMulti\docs\ECOSYSTEM_INTEGRATION_PIPELINE.md`。

---

## 四、 本地已测透、完全锁死的五大工程铁律（严禁 GPT 质疑或反向建议）

### 铁律 1：大一统出口池（Unified Pool）与客户端彻底脱钩
* **彻底废弃 `FengWo.exe`**：客户端内存泄漏、经常假死、无自动化接口，全面弃用；
* **Web Token 直通全量节点**：
  * **专线源 A（蜂窝）**：提取 Chrome 本地存储 `Bearer Ofjt7SVm...`，直接调 `GET https://fengwo.io/api/v1/user/server/fetch` 秒拉 80+ 个全量专线节点；
  * **专线源 B（星辰）**：提取 Chrome LevelDB `Authorization` (JWT)，直接突破普通订阅直链只有 3 个节点的阉割限制，调 `GET https://47.243.129.223:1818/api/v1/user/server/fetch` 秒拉 54 个全量 IEPL/家宽专线；
* **统一大池**：134+ 节点打平混编，界面不露机场名，前台仅显示 Google 与 Claude 业务卡片及启停按钮。

### 铁律 2：主战模型与决策分工已重构
* **全权主战模型**：正式确立为 **Gemini 3.8 Flash (tiered)**，通过本地 Antigravity Tools（`127.0.0.1:8045`）调度，负责全局复杂的网络巡检、同区自愈判定、多模态任务与业务编排；
* **应急兜底模型**：**智谱 GLM-4-flash**（由本地中枢仓库 `D:\GitHub\GLM-4flash` 供给）降为第二梯队纯离线应急备用，仅在网络中断或 Antigravity 整体限流时做极简口头托词与告警，严禁擅自做决策。

### 铁律 3：Antigravity 调度收口原则【前稳后活】
* **前端账号死锁（严格防封号）**：
  Antigravity 原作者自带的公共代理池随机轮询极其简陋，若开启随机轮询会导致同一账号短时间内在不同国家跳跃，触发 Google 异地封号。因此：**6 个活跃 Google 账号坚决保留死锁！一号一固定专属端口通道**；
* **后端虚拟端口路由（Virtual Port Router）**：
  Antigravity 看到的专属端口（如 `21101-21106`），其底层出口由 AgentProxyHub 在**同国家/同大区策略组**内部根据时序置信度（稳定性 40% + 大区合规 30% + 协议健康 30%，7 天一票否决）自动热切与自愈。Downstream 零感知，端口永远通畅。

### 铁律 4：信使分级告警机制
* **普通自愈（绿标）**：同区节点波动、自动热替换 ➔ **后台静默记录，绝不打扰用户**；
* **致命熔断（红标）**：整大区节点全挂、Token 过期、Google 验证码跳脸 ➔ **触发双信使**：
  1. 通过 `127.0.0.1:8766` 呼叫《鲸管家》Live2D 冒大字气泡并在桌面做出委屈动作；
  2. 通过 `127.0.0.1:48921` USB 总线呼叫小米 8 Lite 手机分身在微信直接私聊一帆。

### 铁律 5：干净一刀切，不留软连接
* 彻底抹除旧版 `FengWoBridge` 痕迹，CloakMulti 与 Flow-Tools 下游路径直连新中枢 `AgentProxyHub/data/nodes.json`，配置文件干净清爽，杜绝历史包袱。

---

## 五、 现役 6 个 Google 账号标准化迁移映射清单（用于清洗 `gui_config.json`）

| 账号邮箱 | 账号名称 | 现役历史端口 | 账号固有属地 | 新中枢目标标准化专属通道 | AgentProxyHub 后端挂载策略组 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `korinenox00@gmail.com` | Rag | `22021` | 加拿大 (CA) | `127.0.0.1:21101` | `ProxyGroup-CA-Auto` (加拿大专线同区自愈池) |
| `serendipity4518@gmail.com` | no no | `22024` | 英国 (UK) | `127.0.0.1:21102` | `ProxyGroup-UK-Auto` (英国专线同区自愈池) |
| `hamisujko14@gmail.com` | 01 BOT | `22023` | 法国 (FR) | `127.0.0.1:21103` | `ProxyGroup-FR-Auto` (法国专线同区自愈池) |
| `vxjsjxyxsnvxuxnz75@gmail.com` | 02 BOT | `22010` | 台湾 (TW) | `127.0.0.1:21104` | `ProxyGroup-TW-Auto` (台湾家宽同区自愈池) |
| `393usdb@gmail.com` | Michelle Roberts | `22038` | 墨西哥 (MX) | `127.0.0.1:21105` | `ProxyGroup-MX-Auto` (墨西哥专线同区自愈池) |
| `ucesnq@gmail.com` | William Lewis | `22002` | 美国 (US) | `127.0.0.1:21106` | `ProxyGroup-US-Auto` (美区纯净专线同区自愈池) |

---

## 六、 待落地的各大仓库积压资产明细（等待全量联动）

1. **`AgentProxyHub` 仓库**：
   - 待落地：`core/upstream_fetcher.py`（自动化轮询 fetch 接口拉取无损节点）；
   - 待落地：`config/config.yaml` 策略组模版接入虚拟端口 `21101-21106`；
   - 待落地：`scripts/pool-guard.ps1` 接入置信度评分自动切流。
2. **`Flow-Tools` 仓库**：
   - 待落地：合并不死锁的 `reliability_contract.rs`；
   - 待落地：代理直连由 `21012` 平移至 `21106`（美区纯净通道）。
3. **`CloakMulti` 仓库**：
   - 待落地：合并不阻塞调试解挂守护（`unpause_daemon.py`）；
   - 待落地：CDP 提取 Google Session 直传 Flow-Tools。
4. **`鲸管家` 仓库**：
   - 待落地：在 `src/features/orphan-cleaner/core/rules.ts` 中加入 `agentproxyhub` 和 `mihomo` 白名单；
   - 待落地：在 `src/features/desktop-pet/main.ts` 中开启 `8766` HTTP `/notify` 监听服务。
5. **`手机分身` 仓库**：
   - 待落地：开启 `core/notify_server.py`（48921 端口），监听来自 PC 端的不可逆异常告警 JSON。

---

## 七、 需要 GPT 输出的四大架构任务书规格

请 GPT 严格围绕上述事实，不要发散、不要建议增加人工环节，精准输出以下四份实操规约：

### 任务 1：《Antigravity `gui_config.json` 瘦身与通道标准化 JSON 规范》
* 给出将当前 40KB、26 个历史混乱代理的 `gui_config.json`，精准瘦身为只保留上述 6 个标准化通道的精确 JSON 结构片段（包含 `proxy.proxy_pool.proxies` 与 `account_bindings` 的规范格式），供本地脚本直接无感替换。

### 任务 2：《AgentProxyHub 虚拟策略组与 Mihomo 动态生成契约》
* 针对 `21101-21106` 这 6 个监听端口，定义在 `core/gen-config.ps1` 中生成的 Mihomo 配置结构：每个端口对应一个独立的 `url-test` 或 `fallback` 策略组，严格限定在该端口对应国家的节点子集内，并暴露给 `127.0.0.1:21909` 控制器。

### 任务 3：《Gemini 3.8 Flash 驻场工程师决策提示词与置信度自愈状态机》
* 编写供 Gemini 3.8 Flash 运行的极简高可靠 System Prompt 与严格 JSON 输出 Schema（`{"status": "HEALTHY"|"REBIND"|"QUARANTINE", "target_port": 2110x, "new_node": "...", "notify_level": "SILENT"|"URGENT_ALARM"}`），并规定何时静默同区切换、何时向鲸管家（8766）和手机分身（48921）派发告警。

### 任务 4：《全生态全量上线与各仓库 Git Push 编排顺序》
* 给出涵盖 `AgentProxyHub`、`Flow-Tools`、`CloakMulti`、`鲸管家`、`手机分身` 的一次性全量上线并推送远程分支的操作次序与验收检查点。
