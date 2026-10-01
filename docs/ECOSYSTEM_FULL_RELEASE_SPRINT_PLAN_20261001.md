# 生态全量上线冲刺计划书

> 版本：v1.0｜目标：在保留现役服务和可回退版本的前提下，尽快完成全量上线。
>
> 本计划把“全量上线”定义为：所有工作包通过真实业务验收、统一能力/任务/事件协议接入、完成一次新旧版本回退演练，并在明确的成本、收件对象和授权边界内切换。健康检查、编译通过、mock 通过不能单独作为上线证明。

## 一、当前基线

### 已可复用的已上线能力

- Flow 网关 `8001` 当前运行 PID `35648`，稳定 Release SHA256：`D7DB864B015D0E530A53F8710832CB3A0A833316C26092B6B32ACD1F91F4643A`。
- Flow 已完成 Profile 锁分类、主体邮箱先校验后 upsert、`profile_busy`→409、启动页本机能力值持久化。
- `ucesnq` 已完成一次受控真实同步：HTTP200、目标主体匹配、`hasCookies=true`、`admissionState=validated`；最近一次账号池复查为 6/6 healthy。
- Cloak `7800` 已有准入锁、无凭据 idle 事件和登记账号 reconcile 候选；准入测试 9/9。
- Hub 候选 18/18；pool-guard 候选已 fail-closed，正式网络运行副本未切换。
- Visual Pro 原有 193/193，deep-optimize 12/12；Seedance 84/84、typecheck/build 通过。

### 正式上线不可绕过的阻断

1. WP-00 统一协议未落地：能力注册、任务、事件、预算、幂等、replay、审计和唯一生产账本入口尚未成为共享实现。
2. Hub 事务发布器、真实故障注入、租约排空、切换/回退演练未完成。
3. Flow reliability 尚未接生产 HTTP/DPAPI/任务库/operation 查询，未知提交和重启恢复未闭环。
4. Antigravity recovery 尚未接现有 handler；候选完整测试被缺失 `../dist` frontendDist 阻断；没有真实最小对话验收。
5. Visual Pro 尚无真实 Gemini route/payload/hash 证据；Canvas 尚无真实宿主运行验收。
6. 手机/微信尚无稳定 sender、recipient、conversation 和 delivery ACK；禁止真发。

## 二、上线策略：先核心闭环，再并行补齐外围

### 关键原则

- **不再先做状态文档**：每个阶段必须产出代码、测试和真实交互证据。
- **不改现役源头做实验**：候选目录、独立构建产物、正式运行副本三分离。
- **不先切换网络**：Hub 仍作为候选，FengWoBridge/mihomo 保持现役，直到 Hub 的真实出口和回退通过。
- **不重生未知任务**：unknown 只查询或人工核对；发送失败只重发原 artifact。
- **不绕过身份边界**：主体不一致、跨国漂移、无法确认收件对象、未知费用一律升级。
- **每个工作包以真实代表用例为先**：先跑通一条闭环，再扩展完整测试。

## 三、并行工作流和交付物

### Track 0：WP-00 统一底座（主线，P0）

**目标**：建立唯一、可复用、可审计的能力/任务/事件/账本协议。

**实现顺序**：

1. 建立版本化 schema：`capability`、`task`、`event`、`budget`、`delivery`、`rollback`。
2. 实现能力注册表：`observe / plan / execute / verify / pause / resume / report` 及 `proxy.recover`、`flow.sync_profile`、`flow.query_task`、`antigravity.recover_session`、`visual.deep_optimize`、`notify.wechat`。
3. 实现统一任务状态机：`accepted → persisted → submitted → running → succeeded|failed|cancelled|unknown`。
4. 实现幂等键、版本/CAS、replay 防护、预算 reserve/consume/refund、审计脱敏。
5. 将每个工作包接入适配器，不允许各项目复制一套任务库。

**必须通过的 P0 用例**：未知提交不重生、重复 webhook 去重、预算耗尽无上游副作用、过期操作拒绝、非法能力拒绝、坏账本拒写、CAS 冲突不覆盖。

**交付物**：共享 schema、参考实现、迁移说明、X-01..X-05 逐 Case 证据。

### Track A：Hub 网络托管（P0）

1. 建立正式路径与候选路径的差异清单；确认唯一 `bindings.json` 生产读写入口。
2. 完成事务发布器：跨进程锁、原子写、revision/CAS、journal、目录持久化、损坏拒写。
3. 接入 provider 刷新、严格同国选择、配置解析、热重载、失败回退。
4. 先在隔离副本做真实故障注入：坏 YAML、reload 失败、进程崩溃、并发写、端口失效。
5. 记录每个现役端口/Profile/账号语义不变；使用 `curl --socks5-hostname` 实测国家码、出口和 PID 路径。
6. 完成“旧版→候选→旧版→候选”回退演练，再安排小范围 drain 切换。

**禁止**：跨国 fallback、修改 Antigravity 私库、宽泛进程树强杀、未排空就换绑。

### Track B：Flow 凭据与任务恢复（P0）

1. 将 reliability contract 注册进真实任务存储，不允许旁路三行文件或进程内 Map 作为生产事实库。
2. 实现 DPAPI/本地加密存储、固定任务锁、唯一临时文件、flush+fsync、目录持久化、启动恢复。
3. 接入 HTTP 提交前 `persist-before-send`、真实 `operation_id/output_ref`、轮询查询和 unknown 状态。
4. 实现跨进程 RefreshLeases、账号 generation/CAS、55 分钟 AT 保守 cap 与 expiry provenance。
5. 用 mock 上游完成 200 无 AT、soft-error、429 Retry-After、网络错误、地区 403、未知提交等矩阵。
6. 先以本地授权测试账号跑一条真实“提交→轮询→产物→重启后恢复”闭环，再考虑生产切换。

**上线条件**：重复请求只产生一次上游提交和一次扣费；重启后可查询而非重生；任务取消和 late completion 有明确归属。

### Track C：Antigravity 会话恢复（P1，但必须在对话入口前）

1. 候选补齐 `frontendDist` 所需 `../dist`，仅在候选生成，不能触碰 PID `19868`。
2. 对现有 Gemini/OpenAI/Claude handler 的错误分支接入统一 recovery classifier。
3. 仅对已有 `session_id` 执行解绑/清理 last-used；预算绑定请求上下文，不使用静态业务状态。
4. 保留现有账号出口绑定，跨区不自动漂移。
5. 先做离线 3/3 recovery、7/7 边界，再跑候选完整测试；随后用明确授权账号完成一次最小对话和一次可控恢复。
6. 只在真实对话证据、回退二进制和服务健康均满足时切换。

### Track D：Cloak 自动纳管（P1）

1. 将登录成功事件规范化为 `event_id/dedupe_key/profile/email/binding_revision`，事件不含 Cookie/Token。
2. 修正 idle 通知时序：确认浏览器 seat/锁释放后再通知 Flow，避免 busy race。
3. 接入 Flow 主体校验、binding revision/CAS 和重复同步幂等。
4. 用一个受控 Profile 跑“登录完成→事件→同步→Flow/Antigravity 纳管→重复事件去重”。
5. 保留人工登录、2FA/CAPTCHA 升级边界；不自动绕过验证码或主体不一致。

### Track E：Visual Pro 双模式（P1）

1. 保留原优化路径；Visual Pro 深度优化作为显式用户调用的旁路模式。
2. 将 `scene_service.py` 用户改动与候选路由分离，先做 Owner diff review。
3. 接入真实文件 payload、实际 SHA256、bytes、route/model/channel receipt；metadata/base64 存在不能算理解证据。
4. 建立离线降级：Visual Pro 不可用时原节点功能不受影响，失败结果不缓存成功。
5. 在无付费或最小授权额度内完成一张图片的真实多模态理解；视频按开/中/尾抽样记录覆盖；音频明确支持或 unsupported。

### Track F：Canvas / Seedance（P1）

1. 保留 Seedance 候选已通过的 84/84、typecheck/build。
2. 在宿主中核验插件 `buildHash`、版本、节点输入和真实素材 URI/64 位 hash。
3. 连接 Visual Pro 的显式深度优化入口，不让 Visual Pro 接管画布原生生成路径。
4. 真实运行一条“节点→深度优化→用户确认→原节点应用/撤销”的闭环。
5. 完成宿主回退：旧插件仍可加载，过期建议不得覆盖新稿。

### Track G：面板、手机、微信（P2，后置但独立验收）

1. 面板只展示能力状态、任务状态、事件告警和回退入口；运维复杂动作隐藏到高级入口。
2. 手机/微信先完成只读身份发现和授权会话登记，不发送任何消息。
3. 明确稳定 sender、recipient、conversation、order、task、artifact 绑定。
4. 用两个明确授权会话做交叉测试：同会话有序，跨会话并行，同名联系人/群冲突拒绝。
5. 建立 Outbox、重试原 artifact、webhook 去重、过期事件拒绝、delivery ACK。
6. 仅在用户确认测试对象、消息内容、次数上限和发送窗口后，发送最小真实测试消息。

## 四、推荐执行顺序与退出条件

### 阶段 1：48 小时核心闭环

- WP-00 schema/状态机/幂等骨架；
- Hub 事务发布器与 Flow 任务库接入的最小实现；
- Flow unknown/query/restart 代表性真实闭环；
- Hub 和 Flow 旧版回退点冻结。

**退出条件**：P0 unknown、幂等、CAS、坏账本、预算、取消用例全通过；至少一条真实 Flow 任务重启恢复成功。

### 阶段 2：24 小时身份与对话闭环

- Cloak idle-after-release、主体校验、重复同步；
- Antigravity 候选 dist、handler 接线、最小真实对话；
- 真实会话恢复和失败回退。

**退出条件**：一个受控账号完成登录/同步/对话/恢复；无错号写入、无跨区漂移、无 live 误操作。

### 阶段 3：24 小时视觉与画布闭环

- Visual Pro route/payload/hash/receipt；
- Canvas buildHash、URI、撤销/应用；
- 一张真实图片或视频最小额度验收。

**退出条件**：真实媒体证据完整，Visual Pro 离线不影响原功能，Canvas 可回退。

### 阶段 4：24 小时通知与总切换

- 面板通知状态；
- 微信只读身份→最小真实 ACK；
- 全量切换前排空、备份、版本冻结、回退演练；
- 切换后 30 分钟观察窗和自动回退阈值。

**退出条件**：所有 P0/P1/P2 逐 Case pass；发布清单、回退清单和责任人签字完成。

> 以上是工程工作量窗口，不是对自然时间或外部服务可用性的承诺；任何真实授权、验证码、微信身份、媒体费用等待都单独计时。

## 五、全量切换 Runbook

### T-24h

- 冻结候选 SHA、依赖锁、effective config、schema 版本、PID/路径清单。
- 备份 bindings、任务库、账号状态和当前可运行二进制。
- 确认成本上限、测试账号、媒体对象、微信收件对象和观察人。

### T-2h

- 停止新任务进入切换对象；查询未知任务；排空或明确取消。
- 验证代理端口和国家码；不改变现役 Profile 语义。
- 用只读健康和版本接口确认四个服务。

### T-0

- 先切 WP-00/Hub 事务账本，再切 Flow 任务引擎，再切 Cloak/Antigravity，最后启用 Visual/Canvas/通知适配器。
- 每一步执行 health、版本、最小业务探针；任一步失败立即停止后续步骤。
- 记录切换前后 PID、路径、SHA、账本 revision 和任务计数。

### T+30m

- 观察未知提交、重复扣费、锁竞争、账号主体、代理国家、媒体 artifact 和 delivery ACK。
- 任意 P0 违反：停止新任务，恢复旧入口，保留现场，不删除数据。

### 回退

- 代码回退和数据回退分开执行。
- 先恢复入口和二进制，再恢复兼容的数据版本；新增 order/unknown/binding 不得被旧版本覆盖。
- 回退后重新验证 health、版本、旧任务可读性和现役端口。

## 六、上线阻断阈值

任一项发生即阻止全量：

- 账本损坏可能写空或丢绑定；
- 未知提交会重新生成或重复扣费；
- 账号主体不一致仍可 upsert；
- profile busy 被误判成上游故障；
- 跨国出口漂移；
- Visual/Canvas 无实际 payload/hash/receipt；
- 微信收件对象或 ACK 不稳定；
- 无法恢复上一运行版本；
- 任意候选仍直接修改正式私库或正式进程。

## 七、需要用户一次性确认的事项

正式执行本计划前，只需确认以下四项，避免反复停顿：

1. **测试账号**：允许使用哪个已登录账号完成 Flow/Antigravity/Visual 的最小真实验收；是否允许产生明确的最小媒体消耗。
2. **微信测试对象**：指定唯一测试联系人/群、测试内容、最多发送次数和允许时间窗；未指定则只做只读，不真发。
3. **发布窗口**：允许哪一时间段执行排空、短暂重启和版本切换；窗口外只做候选验证。
4. **成本上限**：图片/视频真实验收的总额度上限；没有上限则不调用付费媒体。

除上述四项外，其余候选实现、测试、证据记录和回退准备可按本计划自动推进；正式生产切换仍以逐项门禁通过为准。
