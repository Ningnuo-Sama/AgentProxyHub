# AgentProxyHub 个人自治管家说明书

> 定位：个人内部使用的统一网络、代理、Agent 编排、成本观察、故障降级和桌宠告警入口。
>
> 交互原则：用户只提出目标，Agent 自动执行；正常状态静默；重要结果通过鲸管家气泡/必要时微信通知。
>
> 本文是其他 Agent 接手时的单一入口。动态状态以运行目录、接口和日志为准，不以本文替代现场检查。
>
> **实现状态口径（2026-10-01 代码审计）**：本文把“代码已实现”“已接入运行链路”“已完成真实验收”严格分开。`✅ 已实现` 仅表示源码中存在并可被调用；`⚠️ 部分/候选` 表示有代码但依赖运行数据、外部服务或正式接入未证实；`❌ 未实现` 表示本仓库没有对应实现。旧章节中的架构目标和拍板事项不是完成证明。

---

## 1. 一句话架构

```text
AgentProxyHub
├─ 网络与代理策略
├─ Agent MCP 统一入口
├─ 供应商/模型/价格与用量观察
├─ Gemini ↔ GLM 自适应降级
├─ 鲸管家桌宠、气泡和事件总线
└─ OpenViking 经验读写

Antigravity Tools  ── 对话模型网关
Flow-Tools         ── Google Flow 生图/生视频
VisualPro          ── 视觉业务、TTAPI/AICost 执行
CloakMulti         ── 浏览器环境与账号隔离
Hermes             ── 微信出站
OpenViking         ── 长期经验与技能
FengWoBridge       ── 正式退役，仅保留极端回退
```

AgentProxyHub 是唯一桌面入口：启动它时联动启动鲸管家；其他程序按已有职责协作，不重复建设平行中枢。

### 1.1 驾驶舱与驻场工程师

默认面板是 `ui/panel.ps1` 的 `APH // GATEWAY OBSERVATORY` 驾驶舱：它展示归一化后的网关情报流，而不是原始日志；支持本地去重、关键词隐藏和主题关注规则。工程师输入区接受自然语言指令，例如“隐藏错误重试”“显示最近出视频的日志”“恢复默认”，规则保存到运行数据目录的 `cockpit_rules.json`。GLM 常态汇报按钮目前只是预留接口，未默认外传日志。

Google 账号锚定与环境→端口绑定账本是两个不同概念，驾驶舱不得混用；面板的内核状态也不等同于业务连通性。

---

## 2. 用户交互契约

### 2.1 默认行为

- 用户不需要逐项确认实现细节；Agent 自主读取现有代码、接口和项目规则。
- 个人内部工具优先最小闭环、低维护、快速上线。
- 代码修改后做语法检查、接口冒烟和核心链路验证；不套用大厂式完整测试矩阵。
- 后续通过真实运行发现 Bug，再做定点修复。
- 正常情况不打扰用户；状态变化、故障、价格变化和自动处置结果通过鲸管家汇报。

### 2.2 需要用户手动参与的动作

- 充值、付款、退款确认；
- 删除账户/数据；
- 修改安全设置；
- 其他不可逆外部操作。

Agent 可以打开官网、导航到目标页面、读取页面状态并报告，但不代替用户完成付款确认。

### 2.3 官网授权操作

用户说：

```text
打开蜂窝官网
准备提取个新机场
准备提取个新中转站
```

Agent 执行：

```text
打开当前可用官网
复用当前用户浏览器页面/授权会话
等待用户自行登录
用户说“好了”后读取授权页面和必要接口
提取配置、能力、价格或状态
进行基础验证
通过对话/鲸管家报告结果
```

不后台全盘扫描浏览器凭据；不默认调用已退役 FengWoBridge API。

---

## 3. 项目与职责边界

| 组件 | 只负责什么 |
|---|---|
| AgentProxyHub | 网络策略、代理池、健康度、价格/用量观察、模型降级、统一 MCP、鲸管家事件 |
| 鲸管家模块 | Live2D、桌面气泡、状态展示、通知消费 |
| AgentProxyHub MCP | Agent 查询状态、获取路线、查询报价、执行批准的轻量动作 |
| Antigravity Tools | 文本/对话模型网关、Gemini/GLM 等对话路由 |
| Flow-Tools | Google Flow 生图、生视频、多账号与媒体落盘 |
| VisualPro | 视觉业务编排、TTAPI/AICost 执行、任务结果回报 |
| CloakMulti/CloakBrowser | 浏览器环境、Google Profile、账号隔离和网页授权 |
| Hermes | 微信连接和消息出站 |
| OpenViking | 长期偏好、架构决策、已验证经验、失败模式 |
| FengWoBridge | 退役，不启动、不作为默认 API；仅极端紧急回退 |

### 3.1 关键原则

- AgentProxyHub 是代理健康、环境绑定和网络策略的单一真理源。
- AgentProxyHub 是人民币报价/用量观察的统一入口；VisualPro、画布、Flow-Tools 不各自维护长期价格真相。
- 画布和业务前端只展示人民币；Kie credits、TTAPI quota、美元、内部倍率只留在适配器内部。
- Agent 负责编排、解释、比较和提出候选更新；规则代码负责计算、状态机、幂等、回退和清理。
- 鲸管家只做通知和可视反馈，不重复管理代理池或供应商。

---

## 4. 网络与代理默认规则

### 4.1 默认模式

```text
规则分流，不是全局代理
国内服务优先直连
Google/海外 AI 默认走代理
普通海外下载先尝试直连，失败再走代理
本地局域网和本地服务直连
大文件和蜂窝网络受流量保护
```

已确认的端口段不得改变：

```text
蜂窝：21001-21080
星辰：22001-22045
```

这些端口涉及 Antigravity 账号粘性绑定与 CloakMulti 账本，改端口段会造成现有环境失效和出口漂移。

### 4.2 代理模式

```text
自动       国内直连、海外 AI 代理、普通下载直连优先
强制直连   尽量全部直连，明确必须代理的请求失败并告警
代理关闭   禁止代理路由，不影响国内直连服务
```

开关是逻辑路由开关，不直接杀代理内核或删除配置。

### 4.3 下载保护

默认按请求类型和大小判断：

```text
小文件：直连优先，失败可代理
中等文件：记录流量，代理下载时提示一次
大文件：Wi-Fi 下直连优先；蜂窝/移动网络默认暂停或阻止
```

具体阈值以运行配置为准，不把本文示例数字当作动态事实。Agent 下载依赖、库、模型或其他文件时，应先通过统一网络路线能力获取 `direct`、`proxy` 或 `blocked` 决策。

### 4.4 代理故障

- 单节点失败：自动选同组健康候选。
- 代理池健康节点归零：标记池不可用并告警。
- 代理池全挂但国内服务可直连：国内请求继续工作。
- 必须代理的外网请求：进入等待/失败状态，不循环硬重试。

---

## 5. Gemini ↔ GLM 自适应降级

### 5.1 归因优先级

必须区分：

```text
代理故障
Gemini 服务故障
Gemini 账号/权限故障
区域限制
响应延迟退化
```

不能把所有错误都归类为代理挂掉。

### 5.2 动态延迟基线

使用 Antigravity Tools 的真实请求摘要，不使用固定“3 秒超时”。按同类请求分组：

```text
provider、model、route、请求类型、流式/非流式、并发级别
```

滚动使用最近约 7 天数据计算 P50/P95、EWMA、首 Token 时间和错误率。样本不足时使用保守默认值；样本积累后自动转动态阈值。

### 5.3 状态机

```text
HEALTHY
  → 单次慢请求：记录，不切换
  → 连续慢请求/错误：DEGRADED
  → 达到动态熔断条件：GEMINI_TRIPPED
  → 冷却后：HALF_OPEN
  → 探测通过：RECOVERING
  → 灰度成功：HEALTHY
```

### 5.4 切换与恢复

- 只对新聊天请求切换到 GLM。
- 已经开始输出的流式请求不强行重发，避免重复计费和上下文断裂。
- Gemini 熔断后冷却，后台用低 Token、无工具、无媒体的探测请求恢复。
- 探测连续成功后按小比例灰度切回；再次失败立即回 GLM。
- Gemini/GLM 切换、恢复和失败均通过鲸管家告警。

图片/视频等付费任务默认不自动跨供应商重提；提交状态未知时先查询原任务/幂等记录。

---

## 6. 人民币报价与用量观察

### 6.1 对外规则

界面只显示：

```text
预计 ¥0.36
实际 ¥0.43
价格已验证
待核价
价格异常
```

不向用户暴露：

```text
credits、quota、美元、内部倍率、原始兑换公式
```

### 6.2 价格能力签名

价格键不是简单的 `provider + model`，而是：

```text
capability + parameters
```

例如：

```text
midjourney.imagine
midjourney.upscale
midjourney.variation
video.generate
image.generate
```

TTAPI Midjourney 按功能收费，功能差异在适配器内部处理；Kie 的 credits/美元/时长规则在适配器内部处理；Flow-Tools 的免费/付费能力统一输出人民币。

### 6.3 价格更新

```text
正常：使用缓存报价
发现异常：核对实际账单/接口/日志
确认变化：更新人民币价格版本，同步新节点
无法确认：保留旧规则并标记待核价
```

价格变化、预计/实际不一致、重复扣费、未扣费和账单脱钩通过鲸管家提示。

### 6.4 任务摘要与生命周期

普通任务摘要只保留 7 天，采用轻量 JSONL/state 文件，不引入重型数据库。摘要只保存：

```text
时间、供应商、能力、状态、预计人民币、实际人民币、耗时、异常类别
```

不保存完整 Prompt、完整响应、签名媒体 URL、Token、Cookie 或节点密码。异常和价格变更摘要可以保留更久，具体以运行配置为准。

---

## 7. Agent 统一入口

Agent 优先通过 AgentProxyHub MCP/本地 API 完成：

```text
查询代理与网络状态
获取目标路线：direct / proxy / blocked / wait
查询人民币报价
查询 7 天用量与供应商比较
核对价格异常
刷新缓存或触发恢复探测
打开指定官网
```

推荐最小工具集合：

```text
proxy_network_status
proxy_network_route
pricing_quote
usage_status
usage_action
browser_open_site
browser_read_page
```

工具表修改后必须重启 MCP 宿主，旧 Agent 不会自动获得新工具。

Agent 工具必须具备：

- 幂等：重复打开、刷新、告警不会产生重复副作用；
- 失败自报：返回稳定错误码、是否可恢复和建议动作；
- 可回退：新规则失败恢复上一版；
- 低噪声：只记录开始、成功、失败、恢复和状态变化。

### 7.1 蜂窝/机场/中转站接入

默认不依赖 FengWoBridge API。流程是：

```text
用户提出“打开官网/准备提取新机场/新中转站”
  → Agent 打开当前可用官网
  → 用户自行登录
  → 用户说“好了”
  → Agent 读取当前授权页面/必要接口
  → 提取可用配置、能力、价格或状态
  → 做基础验证
  → 报告结果并写入允许的运行配置
```

充值由 Agent 打开官网，用户手动完成付款；Agent 不自动确认付款。

---

## 8. 鲸管家事件与通知

AgentProxyHub 内部统一事件总线，兼容旧 HTTP 通知入口。事件类别：

```text
proxy_down
proxy_recovered
gemini_fallback
gemini_recovered
price_changed
billing_anomaly
download_blocked
service_degraded
auto_repair_failed
```

严重级别：

```text
silent    只记录
info      普通气泡
warning   气泡 + 状态标记
critical  气泡 + 必要时 Hermes 微信
```

气泡只给结果，不暴露底层 Token、Cookie、签名 URL、节点密码或长堆栈。

示例：

```text
TTAPI Midjourney 价格已由 ¥0.36 调整为 ¥0.43，已自动同步。

代理池全部不可用，Gemini 已切换 GLM。

Gemini 已恢复，连续探测通过，已自动切回。

当前为移动网络，Agent 请求的大文件已暂停，等待 Wi-Fi。
```

---

## 9. OpenViking 经验治理

### 9.1 进入 OpenViking 的内容

只沉淀：

- 用户长期偏好；
- 已拍板架构决策；
- 有代码/日志/测试证据的稳定事实；
- 可复用的故障解决方案；
- 已确认的失败模式和反模式；
- Agent 接手所需的短运行手册。

### 9.2 不进入长期记忆的内容

- 普通任务流水账；
- 7 天内即可过期的原始日志；
- 完整 Token、Cookie、JWT、API Key；
- 完整签名 URL、节点密码、UUID、私钥；
- 完整 Prompt/Response；
- 未验证猜测；
- 重复告警和一次性临时状态。

### 9.3 晋升流程

```text
原始事件（本地，7天）
  → 日摘要
  → 重复/证据筛选
  → 候选经验
  → 验证
  → 已验证经验
  → 稳定规则/长期决策
```

已有经验优先更新，不重复新建。候选经验不参与默认全局召回；已验证经验按任务定向检索。

### 9.4 经验字段

```text
experience_key
结论
适用范围
证据来源
confidence
verified_count
last_verified_at
回退/失效条件
```

---

## 10. 运行、维护与接手

### 10.1 源码与运行副本

```text
源码：D:\GitHub\AgentProxyHub
正式运行副本：D:\Program Files\AgentProxyHub
```

源码修改不等于正式运行副本已更新。启动入口、运行配置、数据和日志以现场为准。

### 10.2 敏感数据边界

以下只存在运行目录或凭据系统，不提交 Git：

```text
config/config.yaml
data/nodes.json
data/bindings.json
bin/mihomo.exe
bin/*.metadb
logs/
release/*.zip
订阅链接、控制密钥、账号凭据、节点数据
```

### 10.3 端口与账本硬约束

- 蜂窝端口 `21001-21080` 不得变更；
- 星辰端口 `22001-22045` 不得变更；
- `data/bindings.json` 是环境 → 端口锁定账本，与 Antigravity 账号粘性账本不是同一概念；
- 修改绑定账本格式必须同步检查 CloakMulti 的 `cloakmulti/aphub.py`；
- 修改 `mcp/server.py` 后必须重启 MCP 宿主。

### 10.4 最小冒烟

个人工具不做大厂式完整测试。至少验证：

```text
AgentProxyHub 能启动
鲸管家能启动并弹气泡
MCP 能返回代理状态
国内目标可直连
Google/AI 目标按规则走代理
报价可返回人民币或待核价
Flow-Tools/VisualPro 任务摘要可落盘
7天清理可执行
Gemini 故障可切 GLM（若该链路已启用）
```

### 10.5 失败处理

```text
新功能失败 → 保留旧功能
价格更新异常 → 恢复旧价格
代理切换失败 → 回到上一可用路线
浏览器登录态失效 → 停止并提示用户登录
充值/付款页面 → 打开并等待用户手动操作
提交状态未知 → 不自动重复付费任务
```

---

## 11. 当前已拍板事项

- AgentProxyHub 是唯一桌面入口；启动时联动鲸管家。
- 蜂窝、机场、中转站优先网页授权流程；用户说“好了”后 Agent 自动提取并报告。
- FengWoBridge 正式退役，默认不依赖其 API/桥接。
- 充值由 Agent 打开官网，用户手动完成。
- AgentProxyHub 统一网络、代理、价格、用量、异常和 MCP。
- 国内直连；Google/海外 AI 走代理；普通下载直连优先；大文件与移动网络受保护。
- Gemini 异常自动切 GLM，恢复后动态探测并灰度切回。
- Kie、TTAPI、Flow-Tools 等对外统一显示人民币。
- 节点优先复用现有价格接口，坏接口由后端兼容层处理。
- 普通摘要缓存 7 天，异常/稳定经验按治理规则保留。
- Agent 自动接入、分析和维护；用户只接收最终结果和必要异常。
- 个人工具先最小闭环、基础冒烟、直接使用，后续按真实 Bug 修复。

---

## 12. 交接给新 Agent 的执行顺序

```text
1. 读取本说明书
2. 读取 AgentProxyHub/AGENTS.md 与 LOCAL_MAINTENANCE.md
3. 确认源码、运行副本、进程和配置路径
4. 检查当前 Git 改动与运行状态
5. 按任务定向读取 OpenViking 已验证经验
6. 复用现有接口，不重复造轮子
7. 直接完成最小闭环
8. 做基础冒烟
9. 通过鲸管家汇报结果
10. 将稳定新经验按门禁沉淀，不写流水账
```

---

## 13. 代码实现状态（以源码审计为准）

### 13.1 已实现（代码可直接调用）

| 能力 | 证据/入口 | 边界 |
|---|---|---|
| MCP stdio JSON-RPC | `mcp/server.py`：`initialize`、`tools/list`、`tools/call` | 宿主启动时固化工具表，改代码后必须重启客户端 |
| 场景/节点筛选 | `list_scenes`、`list_matched_proxies` | 依赖 `config/scenes.json` 与 `data/nodes.json`；静态评级不是实时可用性 |
| 本地端口 TCP 预检 | `probe_local_ports`、筛选结果 `port_open/ready` | 只证明本地监听，不证明目标站点、地区或账号业务可用 |
| SOCKS5 目标链路测试 | `test_proxy_target` | 真实完成 SOCKS5 CONNECT；不等同完整 HTTP/业务响应验证 |
| 环境→端口幂等绑定 | `bind_profile_proxy` + `bindings.lock` + 原子替换 | 已绑定给其他 Profile 时拒绝抢占；没有解绑工具 |
| 双账本只读解析 | `get_profile_bindings`、`get_antigravity_stickiness` | `bindings.json` 是环境→端口；Antigravity 是账号→出口，后者只读 |
| 一键挂载命令 | `get_proxy_command` | 只生成 PowerShell/Bash/Chrome/Claude Code 命令，不执行注入 |
| 时序置信度巡检 | `core/confidence_engine.py`、`audit_confidence` | 40/30/30 加权、观察钟、漂移与一票否决；只建议，不自动改绑 |
| Google 国家只读核验与建议 | `google_verify_proxy`、`agent_recommend_proxy` | 以 Google Country version 为证据；需要人工/上层批准，`auto_rebind=false` |
| 上游凭据登记与脱敏读取 | `set_upstream_credential`、`get_upstream_sources` | 写入运行目录 `upstreams.json`；默认脱敏，`include_secret=true` 才返回明文 |
| 上游抓取与 LKG 快照 | `core/upstream_fetcher.py`、`refresh_upstream_nodes` | HTTPS、支持 `api_token/subscription_url/profile_path`；失败源保留 last-known-good |
| 节点池同步/重建入口 | `core/sync_nodes.py`，支持 `--rebuild` | 生成/维护 `data/nodes.json`；实际 mihomo 启动仍取决于运行包与配置 |
| 鲸管家 best-effort 通知客户端 | `core/jingguanjia_notify.py`、MCP `notify_jingguanjia` | `127.0.0.1:8766` 默认端点不可用时不阻断代理；不是完整事件总线 |
| 轻量自治状态与安全闸 | `core/autonomy_core.py`、MCP `autonomy_status`/`autonomy_action` | 事件7天清理、开关原子落盘、路由/下载建议；不自动改绑、不执行下载 |
| 人民币报价与网络路线建议 | MCP `pricing_quote`、`proxy_network_route` | 未核验供应商返回“待核价”；仅建议，不发起付费请求或修改系统代理 |

### 13.2 部分实现/候选，不能宣称已完成

| 目标 | 当前事实 |
|---|---|
| AgentProxyHub 正式部署 | `LOCAL_MAINTENANCE.md` 同时保留“正式运行副本迁移目标/尚未部署”与后续迁移记录；必须现场核对 `D:\Program Files\AgentProxyHub`、PID、端口和日志，源码更新不会自动部署 |
| 端口池与成熟面板 | 本仓库代码存在同步和启动脚本，但运行能力依赖 mihomo、geo 数据、`config`/`data`；不能仅凭 README 的发行版描述认定可用 |
| 鲸管家联动 | 仅有 best-effort HTTP notify 客户端；启动脚本未证明已接入全部启动、恢复、价格、降级事件 |
| 价格/用量观察与人民币统一报价 | 已有 `pricing_quote`：本地文本规则可返回 ¥0，其余返回 CNY/待核价；尚无真实供应商用量账本与已核验商业费率 |
| Gemini↔GLM 自动降级 | 本仓库没有对应模型路由状态机/熔断与恢复实现；不可把设计章节当作已实现 |
| 官网授权自动提取 | 本仓库没有浏览器控制器；只能由宿主/浏览器工具另行完成，且需用户登录 |
| OpenViking 经验读写 | 本仓库没有 OpenViking 客户端或写入实现；“治理规则”是文档约定 |
| 手机/局域网网关 | 本仓库没有可核对的网关服务入口；README 中的地址不能作为当前运行证明 |
| 自动注入 P1/Cloak/AdsPower 等浏览器 | 没有对应 injector/适配器实现；MCP 只返回命令或写环境绑定账本 |
| 统一事件总线/微信出站 | `jingguanjia_notify.py` 仅提供 HTTP best-effort 通知；Hermes 微信发送、ACK、重试和事件持久化未在本仓库实现 |
| 7 天任务摘要与清理 | 本仓库未发现统一任务摘要 schema、生命周期清理器或价格账单存储实现 |

### 13.3 当前 MCP 工具完整清单（以 `mcp/server.py` 的 `TOOLS` 为准，共17项）

| 工具 | 作用 | 写入/副作用 |
|---|---|---|
| `autonomy_status` | 读取自治状态快照 | 只读 |
| `pricing_quote` | 返回人民币报价或待核价结果 | 只读，不发起付费调用 |
| `proxy_network_route` | 返回直连/代理/阻断建议 | 只读，不改系统代理 |
| `autonomy_action` | 设置自治开关、清理事件、查看摘要 | 写自治状态或事件文件，不改绑定 |
| `notify_jingguanjia` | 发送鲸管家气泡通知 | 本机 HTTP best-effort |
| `google_verify_proxy` | 通过 Google Country version 只读验证端口国家 | 无绑定写入 |
| `agent_recommend_proxy` | 汇总 Google 核验与置信度，给出 `retain/hold` 建议 | 不自动换绑 |
| `refresh_upstream_nodes` | 拉取已登记上游并更新快照；支持 `dry_run` | 非 dry-run 写快照，失败保留旧快照 |
| `set_upstream_credential` | 登记/更新上游源 | 写 `upstreams.json`，凭据敏感 |
| `get_upstream_sources` | 读取上游源及状态 | 默认 Token 脱敏；明文读取需显式参数 |
| `list_scenes` | 列出场景靶场 | 无 |
| `list_matched_proxies` | 按场景/国家/评级筛选并补充端口探活、快照年龄、绑定信息 | 只读 |
| `get_proxy_command` | 生成终端、Chrome、Claude Code 挂载命令 | 不执行命令 |
| `bind_profile_proxy` | 锁定 Profile→端口 | 写 `bindings.json`，带跨进程锁与原子写 |
| `get_profile_bindings` | 读取环境账本及 Antigravity 账号粘性 | 只读 |
| `test_proxy_target` | 经 SOCKS5 测试目标主机连通和延迟 | 只读网络访问 |
| `audit_confidence` | 读取置信快照；`refresh=true` 触发 `confidence_engine.py` | 刷新会写 `confidence_state.json`，不改绑 |

> 注意：当前 `proxy_network_route`、`pricing_quote` 已进入 `TOOLS`，但仍是只读建议/待核价能力；`usage_status`、`usage_action`、`browser_open_site`、`browser_read_page` 仍未在本仓库实现。宿主工具表在客户端启动时固化，更新后必须重启 MCP 消费方。

### 13.4 新模块运行方式与最小验证

```powershell
# 进入源码根目录
cd D:\GitHub\AgentProxyHub

# MCP：stdio 服务（不要把普通日志写到 stdout）
python mcp\server.py

# MCP 端到端自测（临时数据目录，不污染运行数据）
python mcp\test_mcp.py

# 节点池同步；需要时先调用 PowerShell 建池脚本
python core\sync_nodes.py
python core\sync_nodes.py --rebuild

# 时序置信度：日常只巡检绑定 + S/A；全量需显式指定
python core\confidence_engine.py --scope bound
python core\confidence_engine.py --scope all
python core\confidence_engine.py --show

# 鲸管家健康等待/发送 best-effort 通知
python core\jingguanjia_notify.py --wait-health
python core\jingguanjia_notify.py --text "AgentProxyHub 状态已更新"

# 启动脚本（会打开面板；是否实际启动内核取决于 bin/config/data）
启动AgentProxyHub.bat
scripts\mcp-server.bat
```

运行前检查：`config/scenes.json`、`data/nodes.json`、`data/bindings.json`、`bin/mihomo.exe` 与 geo 数据是否存在；不要把真实 Token 放进命令行或 Git。正式副本与源码分离，必须单独核对部署状态。

### 13.5 验证分级

- **代码/语法**：`python -m py_compile mcp/server.py core/*.py`（只能证明可编译）。
- **MCP 契约**：`python mcp/test_mcp.py`（临时目录；覆盖握手、列举、筛选、命令、上游 dry-run/登记/读取）。
- **真实出口**：对具体端口运行 `test_proxy_target`，必要时再用 `google_verify_proxy`；监听和静态 `nodes.json` 不足以证明可用。
- **真实部署**：核对运行副本路径、进程 PID、`logs/panel.log`、端口探活和实际目标请求；源码修改不等于已发布。
- **边界**：本次文档审计没有启动服务、迁移运行副本、提交凭据、切换端口或验证付费供应商能力。

---

## 14. 变更记录

- 2026-10-01：汇总已拍板的 AgentProxyHub 唯一入口、鲸管家合并、浏览器授权、FengWoBridge 退役、网络分流、人民币报价、7 天缓存、模型降级、Agent MCP 和 OpenViking 治理规则。
- 2026-10-01：按源码审计补充已实现/未实现标记、当前 12 项 MCP 工具、上游/LKG/置信度/通知模块运行说明；明确目标契约不等于代码完成。
