# 多项目代理与账号生态整合基线

> 版本：2026-09-30 v1
> 目的：收敛 AgentProxyHub、CloakMulti、Flow-Tools、Antigravity Tools、GLM-4flash 的职责、事实状态、落地边界与验收顺序。
> 原则：本文件是整合决策基线，不替代各项目的本地维护说明；未验证内容不得写成已实现。

## 1. 结论先行

这组项目的总体方向合理，但原《AUTONOMOUS_PROXY_INTEGRATION_SPEC》不能原样执行。需要从“全自动换线/全自动凭据推送”收敛为：

1. **AgentProxyHub 是网络出口事实源**：维护节点测绘、端口池、环境→端口绑定、健康与置信度审计；不因评分自动改绑老账号。
2. **CloakMulti 是人工/自动登录入口**：维护指纹环境和浏览器登录态；使用 AgentProxyHub 的端口，但不拥有代理真理账本。
3. **Flow-Tools 是 Google Labs 媒体网关**：维护媒体账号池、Cookie/Session 提取、点数和生成调度；当前可靠路径是已存在的 `sync-profile`，资料浏览器关闭后读取资料，不是已验证的 CDP 内存热推。
4. **Antigravity Tools 是 LLM 网关**：维护自己的账号凭据、会话粘性、模型调度和代理池。不得把 Flow/Cloak 的 SessionToken 或 OAuth 假定写入 `user_tokens.db`；凭据目录以当前运行版本实际的 `accounts.json` / `accounts\*.json` 为准。
5. **GLM-4flash 是决策建议/审批层**：消费 AgentProxyHub 的只读置信度结果，输出迁移建议或风险解释；不直接改绑定、不直接接触凭据、不自动执行跨区切换。
6. **手机/微信是告警通道，不是第一阶段控制面**：先验证 webhook 接收、去重、告警升级和回执，再考虑自动输入微信。

核心落地形态是“只读观测 → 建议 → 人工/显式审批 → 单项目执行 → 真实验收”，而不是多项目互相写配置。

## 2. 已核实的事实状态

### 2.1 运行实例

| 组件 | 当前实测 | 证据/备注 |
|---|---|---|
| AgentProxyHub/mihomo | `D:\Program Files\AgentProxyHub\bin\mihomo.exe`，监听 `127.0.0.1:21909` | 当前生产实例存在；源码 `D:\GitHub\AgentProxyHub` 工作区有未提交改动 |
| CloakMulti | `D:\GitHub\CloakMulti\bin\CloakMulti.exe`，GUI 监听 `127.0.0.1:7800` | 当前运行的是源码项目壳，不是独立 Program Files 副本 |
| Flow-Tools | `D:\GitHub\Flow-Tools\src-tauri\target\release\flow-tools.exe`，监听 `127.0.0.1:8001` | 当前实际运行路径与维护文档中的 `merged-candidate` 不一致，需补登记 |
| Antigravity Tools | `D:\Program Files\Antigravity Tools\antigravity-tools.exe`，监听 `:8045` | 健康判据必须使用 `/health`，不能只看进程 |
| 告警入口 | `127.0.0.1:48921` 当前有监听进程 | 仅证明端口存在，不证明微信告警闭环已验收 |

### 2.2 数据事实源

- AgentProxyHub 源码账本：`D:\GitHub\AgentProxyHub\data\bindings.json`，当前有实际数据。
- AgentProxyHub 正式运行目录账本：`D:\Program Files\AgentProxyHub\data\bindings.json` 当前为空对象，说明“源码账本”和“运行账本”存在明显撕裂风险；后续必须明确唯一运行读写路径，禁止业务方凭默认路径猜测。
- Antigravity 当前账号数据：`C:\Users\1\.antigravity_tools\accounts.json` 与 `accounts\*.json`；`user_tokens.db` 是另一类内部数据，不能按 Cloak 文档的推断直接当作 OAuth 注入目标。
- Flow-Tools 当前账号/资料：`%LOCALAPPDATA%\FlowTools\accounts.json` 与 `browser-profiles.json`。
- `bindings.json` 是 AgentProxyHub 与 CloakMulti 的共享协议文件，任何格式变更必须两边同步并做并发写保护；Antigravity 的账号粘性绑定不是同一账本。

## 3. 已发现的设计冲突与修正

### 3.1 “虚端口热切”与账号身份粘性冲突

固定下游端口只解决配置稳定，不等于固定出口身份。若策略组在底层自动选择另一国家/大区节点，Google 看到的仍是身份迁移。尤其已有事故证明跨洲切换会导致授权撤销和账号报废。

**修正**：

- AgentProxyHub 可以自动做健康探测、同国/同大区候选推荐和坏节点隔离。
- 对已有账号绑定，默认只读推荐；不自动改绑。
- 同国同大区出口 IP 轮换也要记录，只有明确策略允许时才执行“同国重锁”；跨国/跨大区一律熔断并告警。
- `AUTO-POOL` 只能作为无账号身份场景或经明确授权的短期通用出口，不能默认承载主力 Google 账号。

### 3.2 凭据“热推”方案证据不足

Cloak 文档提出 CDP `Network.getCookies` 与双端 HTTP 热装载，但当前代码证据显示：

- CloakMulti 已有 CDP 开关和 AgentProxyHub 绑定能力，但未发现已完成的 `Network.getCookies` → Flow/Antigravity 双推实现。
- Flow-Tools 已有 `/api/manage/sync-profile`、`reload`、资料池和账号入库逻辑；可靠路径仍要求资料浏览器关闭以释放 `instance.lock`。
- Antigravity 已有账号代理池和粘性会话能力，但不能据此推断存在安全的外部 OAuth 热注入契约。

**修正**：第一阶段不做跨程序凭据搬运。先把“已登录资料 → Flow sync-profile → 点数/生成验收”固化；Antigravity 账号纳管另立契约，凭据只经其官方/现有受支持导入路径。

### 3.3 AgentProxyHub 置信度引擎边界

`audit_confidence` 已明确是只读审计，且“高分只推荐、不自动改绑”。这与原路线图 Phase 1 的自动热切不兼容。

**修正**：GLM-4flash 只消费审计结果生成迁移建议书；建议书必须包含原绑定、候选端口、国家码、置信度、漂移历史和风险等级。执行由人工或显式批准的编排器完成，且每次只改一个账号/环境并回读验证。

### 3.4 维护文档与运行状态不一致

当前至少存在：

- AgentProxyHub 源码 `data` 与正式运行副本 `data` 内容不一致。
- Flow-Tools 当前运行二进制是 `target\release`，维护说明登记的是 `target\merged-candidate`。
- Antigravity 交接中的模型/账号表属于时间快照，不能代替当前 `/health`、日志和实际路由验证。

**修正**：将“运行版本登记”作为落地前置工作，记录 PID、exe 路径、Git SHA、数据目录、监听端口、探活结果和回退版本；在登记完成前不做跨项目自动化。

## 4. 统一职责与接口契约

```text
上游机场/节点
      │
      ▼
AgentProxyHub（网络唯一事实源）
  nodes / bindings / confidence / probe
      │ 只读查询 + 显式绑定操作
      ├── CloakMulti：创建/登录指纹环境
      ├── Flow-Tools：媒体账号与生成
      └── Antigravity：LLM 账号与会话
              │
              └── 只读健康/错误事件
                      ▼
                GLM-4flash 建议层
                      │ 建议/审批，不持凭据
                      ▼
                 人工或受控执行器
```

### 最小契约

1. `bindings.json`：唯一语义为“profile/environment → local port”，采用原子写 + 文件锁；不放 OAuth、Cookie、Access Token。
2. AgentProxyHub MCP/API：提供端口候选、真实 TCP 探活、置信度审计、当前绑定读取；自动化调用默认只读。
3. Flow-Tools：对外只使用已存在且鉴权的 `/health`、`/api/manage/sync-profile`、`/api/manage/reload`、生成接口；不新增未验证的 `inject-account` 作为前置依赖。
4. Antigravity：对外只使用其现有管理 API/CLI 和 `/health`；账号凭据写入必须由项目自身代码完成并备份回读。
5. 告警事件：统一字段 `event_id、severity、component、profile、port、country_before、country_after、reason、created_at、dedupe_key`；告警系统不接收原始 Token/Cookie。

## 5. 推荐落地路线

### Phase 0：事实收敛（现在，必须完成）

- 登记四个运行进程的真实 exe、PID、端口、健康结果和数据目录。
- 解决 AgentProxyHub 源码账本/运行账本的单一读写路径问题；先备份，禁止直接覆盖。
- 登记 Flow-Tools 当前实际二进制 SHA 与候选目录，确认不是旧实例占用 8001。
- 将所有新增设计文档标成“方案/未实现”，避免 70%/30% 口径继续误导。

**完成标准**：只读资产表能在新会话复现；四项 `/health` 或等价探针与 PID/路径一致；没有任何凭据写入仓库。

### Phase 1：只读网络控制面

- AgentProxyHub 完成节点重测、快照年龄、真实端口预检和置信度审计。
- CloakMulti 只调用端口池分配/绑定，继续保持一环境一端口；不自动换线。
- Flow-Tools 与 Antigravity 增加“生成前只读网络审计”或外部审计脚本，失败只阻断并告警，不改绑。

**完成标准**：模拟坏节点、陈旧快照、跨区漂移时能准确阻断；正常同区请求真实闭环通过。

### Phase 2：单项目账号闭环

- 先固化 CloakMulti → Flow-Tools 的现有 `sync-profile` 路径：关闭资料、释放锁、调用同步、回读账号状态/点数、真实生成。
- 新增 CDP 在线凭据提取前，必须先定义最小凭据协议、内存生命周期、审计与撤销，并分别在测试账号上验证；默认不把原始 Cookie 落日志。
- Antigravity 单独设计“受支持账号导入契约”，不复用 Flow-Tools 的 SessionToken 载荷。

**完成标准**：一条测试账号链路可重复执行，失败可回滚，不影响现役账号和网关。

### Phase 3：建议与审批

- GLM-4flash 读取 `audit_confidence` 和错误事件，输出结构化迁移建议。
- 默认模型锁定 `glm-4-flash`；建议层不自动执行。
- 审批记录包含建议输入快照、批准人/时间、执行结果和回滚点。

### Phase 4：告警闭环

- 先实现本机 webhook、去重、升级和落盘；再接 Root 手机/微信。
- 账号二次验证、跨区漂移、机场整体失效、连续失败达到阈值时只做隔离和告警，不进行无界重试。

## 6. 明确暂缓事项

- 暂缓“同区虚端口自动热切老账号”。
- 暂缓 CloakMulti 同时向 Flow-Tools 和 Antigravity 自动注入原始凭据。
- 暂缓把 `user_tokens.db` 当作 Antigravity OAuth Refresh Token 注入目标。
- 暂缓自动改写正式运行副本、自动部署和自动推送远端。
- 暂缓微信 Frida/输入自动化作为控制面；先做可靠告警。

## 7. 跨项目验收矩阵

| 用例 | 预期 | 必须证据 |
|---|---|---|
| Hub 健康 | 端口真实可连、快照不过期 | TCP 探测、出口 IP/国码、日志 |
| 绑定一致 | Cloak/Hub 看到同一 profile→port | 双方回读 `bindings.json` |
| 跨区漂移 | 阻断，不自动换线 | 原/现国码、告警、无配置写入 |
| 同区换 IP | 按策略记录或显式批准 | 置信度变化、审批记录、回读 |
| Flow 导入 | sync-profile 成功、点数可见 | `/health`、HTTP 结果、TaskLog、真实生成 |
| Antigravity | `/health` 正常、真实请求走预期端口 | 路由日志、账号绑定、请求结果 |
| GLM 建议 | 只产生结构化建议 | 模型锁定、输入快照、无副作用 |
| 告警 | 去重、升级、可回读 | webhook 事件、手机端回执（后置） |
| 回滚 | 旧二进制/数据可恢复 | 备份路径、旧版本探活、恢复演练 |

## 8. 当前最优先执行清单

1. 建立真实运行清单并修正本文件中的路径登记。
2. 处理 AgentProxyHub 源码账本与运行账本的分裂问题，先只读比对和备份，不直接覆盖。
3. 为 Flow-Tools 当前运行版补充“版本登记/候选切换”维护记录。
4. 在不改生产配置的前提下完成 AgentProxyHub → GLM-4flash 的只读建议原型。
5. 用一个测试 Profile 完成 CloakMulti → Flow-Tools `sync-profile` 重复验收。
6. 四项验收通过后，再决定是否实现任何热装载或自动执行器。

## 9. 证据等级

- **已实测**：本机进程/端口/文件检查结果，以及各项目维护文档中有明确验收证据的功能。
- **代码存在**：源码中有端点/模块，但未代表当前运行实例已加载或真实链路已通过。
- **方案设计**：设计文档提出但尚未在代码和真实运行实例中闭环的功能。
- **待核验**：历史交接快照、旧路径、旧 PID、旧账号表和未回读的部署结论。
