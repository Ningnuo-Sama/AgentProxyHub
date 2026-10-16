# PUSH NOTES · 2026-10-17 · AgentProxyHub

## 本次推送

- 目标：`https://github.com/Ningnuo-Sama/AgentProxyHub.git` 分支 `main`（**公开仓**）
- 起点：`9f0a180 perf(config): AUTO-POOL 探测瘦身 124→4 节点，治理后台探测流量`
- 变更规模：**15 个文件修改 + 12 个文件新增**（`git diff --stat` 计 1617 插入 / 323 删除）
- 本自述文件为本次推送的收尾提交

## 版本背景

2026-10-14 ~ 10-17 发生账号损失（可用账号 **10 → 6**）。Google 侧以
`403 PERMISSION_DENIED` / `reason: TOS_VIOLATION` / `domain: cloudcode-pa.googleapis.com`
移除账号，与 09-29 的 OAuth 层 `invalid_grant` 属**两次不同决策出口**。

本次为「**保号优先**」专项治理，核心结论是：**规则写在文档里不等于规则生效** ——
两次事故之间唯一不变的变量就是「同一类规则被写了两遍、却从未被强制执行」。
因此本版的工程重心是**把规则做成会拒绝的硬门禁**，而不是继续写告警。

## 版本内容

### 一、写操作门禁：拒绝即不写（fail-closed）

| 文件 | 说明 |
|---|---|
| `core/write_guard.py`（新增） | 六类拒绝条件：**契约缺失 / 死号 / 跨洲 / 锁区 / 粘性端口 / 密度**；`--self-test` 22 用例 |
| `core/aphub_lock.py`（新增） | 跨进程文件锁（`LK_NBLCK` + 超时 + 可重入）；**锁失败即放弃写入并告警**，绝不在锁失败后落盘 |
| `mcp/server.py` | 三个真实写点（`bind_profile_proxy` / `auto_rebind_profile` / `set_upstream_credential`）接入共用前置闸，顺序即优先级；拒绝形态统一为 `success/ok=false` + `refused_reason` + `gate`，并向 EventStore 落 `gate_refused` |
| `core/hot_swap_executor.py` | `hot_swap_port_node()` 在**任何副作用（备份/改配置/热重载）之前**接闸；`auto_heal_port` / `scan_and_heal_all` 自动继承 |

接线过程中修掉两个真实缺陷：
1. 区域比较只认 ISO-2，而实测判国字段是全名 ⇒「同国」被误判成「跨洲」而误拒（两侧统一经 `normalize_cc` 归一）；
2. 用目标 proxy 名反推端口号做粘性校验，而**一个出口可服务多个端口**（实测 `fw-21011` 同时服务 3 口）⇒ 端口被误判「改号」；改为校验该业务口自身的 `in-<port>` / `in-http-<port>`。

### 二、端口映射冻结：防「一次重建、整表重排」

- `core/gen-config.ps1`：新增 `-AutoPoolInterval` / `-AutoPoolProbeNodes` 参数化；AUTO-POOL 探测 **124 → 4 节点**（约 0.1 MB/天）
- **端口钉定锁表**（`data/port_map_lock.json`，`scope.mode=all`，**124 口全量冻结**）：锁表内端口按指纹钉回原节点并保留原 proxy 名；指纹在订阅里找不到时 **fail-closed**（保留原定义、不重排）
- `ui/panel.ps1`：订阅刷新检查由 **12 秒 → 12 小时**；`Sync-FromHoneycomb` 首行加 **fail-closed 闸门**（自动重建默认关，改 `true` 即回到旧行为）
- 修掉一个结构性缺陷：运行副本的 `gen-config.ps1` 曾**缺失 UTF-8 BOM** ⇒ 在 PowerShell 5.1 + ACP 936 下**整脚本解析失败**（44 个 ParserError），即「自动重建」此前根本不可执行。补回 BOM 后恢复可执行，并由上述锁表兜住重排风险。

### 三、账本、契约与联动

| 文件 | 说明 |
|---|---|
| `core/ledger_watch.py`（新增） | L0 只读体检 13 项 + 契约守卫 G1~G17；全程 0 出网字节 |
| `tools/port_linkage_sync.py`（新增） | AT ↔ FlowTools ↔ 环境侧**只读比对**同步器，**默认只报不改**（实测三处可写账本哈希全程未变） |
| `ui/panel-ledger.ps1`（新增） | 账本视图：出口 IP(账本) / 判国(Google) / 账号-密度 / 契约-退用 / 归属-冻结 / 探龄 |
| `core/model_router.py` | 模型路由改为**按策略条目的 provider 选择传输**，不再把日常档写死为本地传输 |
| `core/confidence_engine.py` / `core/upstream_fetcher.py` | 判国与上游快照路径加固 |
| `core/jingguanjia_notify.py` | 鲸管家通知通道 |

判据一律**复用既有唯一权威**，不新增第二套定义：密度 = `core/write_guard.py::MAX_ACCOUNTS_PER_EXIT`（**= 2**，即「每出口 IP 的 live 账号数 ≤ 2」）。

### 四、驻场工程师与告警

- `core/resident_scheduler.py`：告警**先经模型总结为自然语言**再推送（不再把检查项编号 / 守卫代号 / 事件 UUID 原样甩给用户）；**同指纹 24 小时只推一次**；状态文件缺失/损坏时**不静默吞掉**（改为当次允许推送）
- `config/model_policy.json`：日常档模型由本地网关切换为**本地 AT 网关**
- `core/alert_dispatch.py`：鲸管家 + Hermes 微信**双通道**，均为**双条件校验**（鲸管家 `GET /health`==200 且 `POST /notify`==202；Hermes `gateway_state.json` running 且 weixin connected 且发送返回 `success=true`）；投递失败落 `data/alerts/undelivered.jsonl`

## 洁净度

- **工作区**：推送前仅含本次变更；无 `__pycache__` / `*.pyc` / 日志 / 临时产物。`.gitignore` 已覆盖 `config/config.yaml`、`data/`、`bridge.json`、`scratch/`、`logs/`、`*.log`、`*.bak*`、`*.dpapi`、`bin/`、`release/`。
- **凭据审查**：对全部待提交文件做 8 类凭据特征扫描。命中 2 处，均在 `mcp/server.py`，为**检测 OAuth token 的前缀字面量**（`token.startswith("ya29.")` 等）与注释，**非真实凭据**。
- **隐私审查与就地脱敏**（本仓为公开仓）：
  - `scripts/rebind_exit.py`：用法示例中的真实账号邮箱 → 占位符
  - `core/write_guard.py`（自测固定数据）与 `tools/port_linkage_sync.py`（注释与断言描述）：真实出口 IP → RFC 5737 文档保留地址 `203.0.113.10`
  - **两棵树同步修改**；`py_compile` 通过、`write_guard --self-test` 通过
- **未包含**：`scratch/`（内部审计报告，含出口 IP 与账号别名）与 `data/` 账本 —— 按公开仓边界**不推送**。

## 已知遗留（未在本版解决）

- `core/write_guard.py` 两棵树（运行副本 / 源码仓）内容**不完全一致**，需按「运行副本为权威」收敛。
- 部分端口的上游节点已失效（TLS `SSLEOFError` / HTTP 502），回钉按契约 **fail-closed 不执行**（无合规候选不许回钉）。
- 账号级工具链能力缺口：环境侧账本**无 move 语义**、工具集**无 unbind**、AT 仅支持整配置回写。
