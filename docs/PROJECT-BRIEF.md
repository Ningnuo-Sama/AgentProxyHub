# AgentProxyHub 项目整合简报（Agent 交接总览）

> 用途：多 Agent 并行开发时的**认知对齐基线**。任何 Agent 接手本项目前先读完本文，再读 `AGENTS.md` 与 `LOCAL_MAINTENANCE.md`。
> 维护约定：每次结构性变更（新模块/新账本/新端口约定）后由执行 Agent 更新本文并随代码一起提交。
> 最后更新：2026-09-30 · 提交 `0ac2bf5`

---

## 一、这个项目是什么（一句话）

**本机多出海业务的代理调度中枢**：把蜂窝（FengWo）/星辰（Xingchen）两个机场订阅打平成「一节点一独立本地端口」的 mihomo 端口池，供 Antigravity Tools、Flow-Tools、CloakMulti、Claude/Cursor 等 Agent 客户端按账号粘性取用，并提供 MCP 工具让 AI 直接调度。

## 二、三份副本，谁是真身

| 副本 | 路径 | 角色 |
|---|---|---|
| **源码仓库** | `D:\GitHub\AgentProxyHub`（本地分支 `main`，自研无上游） | 唯一改代码的地方；改完提交、push 到 `ningnuo-dot/AgentProxyHub` |
| **正式运行副本** | `D:\Program Files\AgentProxyHub` | 开机自启实际跑的；**改源码 ≠ 已部署**，需同步部署 |
| **退役前辈** | `D:\Program Files\FengWoBridge` | 2026-09-29 已被本项目替代退役，仅作回滚备份；其 `Feng` 客户端进程仍是出口上游，别动 |

## 三、核心资产与硬约束

### 端口池（绝对不许改段）
- `21001-21080`：蜂窝出口（SOCKS5）；HTTP 伴生 `31xxx`
- `22001-22045`：星辰出口（SOCKS5）；HTTP 伴生 `32xxx`
- `39999`：智能规则总线（混合 HTTP/SOCKS5）
- **Antigravity 7 个账号粘性绑定直写这些端口号，改段 = 全部失效 + IP 漂移风控**

### 数据账本（都在 `data/`，严禁入 Git）
| 文件 | 语义 | 写方 |
|---|---|---|
| `nodes.json` | 静态测绘快照：单次巡检的出口 IP/国码/ASN/Google 判定国/**送中标记**/S-A-F 评级 | 巡检引擎（`sync_nodes.py --rebuild`） |
| `bindings.json` | 环境→端口锁定账本 | 本项目 MCP **与 CloakMulti `aphub.py` 共写**（有 `bindings.lock` 文件锁），改格式必须两边同步 |
| `confidence_state.json` | **时序置信度账本**（2026-09-30 新增）：漂移史、观察钟、延迟样本、加权分 | `core/confidence_engine.py` |
| Antigravity 账号粘性 | `C:\Users\1\.antigravity_tools\gui_config.json` 的 `account_bindings` | 与上面两套账本是**三回事**，本项目只读 |

### MCP 工具表（`mcp/server.py`，共 7 个）
`list_scenes` / `list_matched_proxies` / `get_proxy_command` / `bind_profile_proxy` / `get_profile_bindings` / `test_proxy_target` / **`audit_confidence`**（新）
⚠️ 工具表由宿主启动时固化——改完 `server.py` 必须重启 Agent 客户端才生效。

## 四、置信度引擎（2026-09-30 Phase 1 已上线，提交 `0ac2bf5`）

### 解决什么问题
蜂窝上游会**无通知偷换节点出口**（已实锤：21050 瑞士→哥伦比亚、21030 德国→菲律宾），静态测绘快照跟不上，导致号池生图触发跨国漂移熔断、且陈旧快照会把好端口误判送中（22002 实例）。

### 设计（已评审定稿，勿重复设计）
- **三维加权**：物理稳定性 40% / 大区合规 30% / 协议健康 30%（协议与履约已合并，防双重惩罚）
- **观察钟分段**：首次见到出口起计时，24h→基础分 60、48h→80、72h→100（S 级置信）
- **漂移分级**：洲际漂移 = 一票否决 + 7 天禁用；同大区跨国 −30 分并重置观察钟；同国换 IP −10 分
- **一票否决**：送中（静态快照标记）/ 离线（连续 3 次探测失败）/ 洲际禁用期未满 → 总分 0（F 级）
- **铁律：引擎只打分推荐，绝不自动改绑端口**。老号（已有粘性绑定）迁移必须走上层决策（GLM-4flash 决策智能体 / 人工），且高置信度本身不构成强切理由——IP 粘性权重高于跑分

### 用法
```
python core/confidence_engine.py --scope bound   # 日常巡检：现役绑定 + S/A 级
python core/confidence_engine.py --scope all     # 全量 125 端口
python core/confidence_engine.py --show          # 只读看快照
```
MCP 侧：`audit_confidence { refresh?: bool, only_vetoed?: bool, min_score?: number }`

### 首跑实测战果
| 端口 | 判定 | 事实 |
|---|---|---|
| 21030「德国专线」 | ❌ 洲际漂移否决 | 已漂到菲律宾 `61.245.11.166`（旧 S 级标记作废） |
| 21050「瑞士专线」 | ❌ 洲际漂移否决 | 已漂到哥伦比亚（Flow-Tools 号池 09-30 事故根因之一） |
| 22002（ucesnq 现役） | ❌ **误伤** | 静态快照标记的是旧送中 IP，实测已是美国稳定出口 → 需重测绘 |
| 21014 美专线 | ✅ C 56.1 | IP 稳定，观察钟计时中，72h 后自然升 S |

## 五、多 Agent 并行提交协调（当前在场者）

| 工作 | 载体 | 状态 |
|---|---|---|
| 置信度引擎 Phase 1 | `core/confidence_engine.py` + `mcp/server.py` | ✅ 已提交已推送（`0ac2bf5`） |
| AutoPilot 工作流 | `docs/auto-pilot-workflow.html/.json`（未跟踪） | 进行中（其他 Agent） |
| `scripts/pool-guard.ps1` | 工作区有未提交修改 | **非本人改动，未触碰**，归属待认领 |
| GLM-4flash 决策智能体 | `D:\GitHub\GLM-4flash`（独立仓库） | 对接中；将作为迁移建议层消费 `audit_confidence` |

**协作规矩**：动 `bindings.json` 格式必须同步 CloakMulti；动端口段直接禁止；提交前 `git status` 认领清白；`data/`、`bin/`、`logs/`、`release/` 永不入 Git。

## 六、待办清单（按优先级）

1. **重跑节点测绘**刷新 `nodes.json`——修复 22002 误伤 + 21030 陈旧 S 级标记（`sync_nodes.py --rebuild`）
2. **注册定时巡检**：Windows 任务计划 2h 一次 `--scope bound`（S/A 级 2h、备选 6h、冷门 24h 的分层轮询可后做）
3. **GLM-4flash 对接**：决策智能体消费 `audit_confidence` 产出《迁移建议书》（画像最小距离匹配：同国>同大区>高置信兜底，老号强制人工/Agent 审批）
4. **Flow-Tools 侧轻量集成**：生图熔断前查一次置信度快照做预警（只读）
5. **全局 git 代理修复**：`git config --global http.proxy` 仍指向失联的 `127.0.0.1:7890`，建议改 `http://127.0.0.1:39999`（待用户确认）

## 七、跨项目联动速查

- `D:\GitHub\CloakMulti`：`aphub.py` 共写 bindings.json；其 profiles 是 Flow-Tools 指纹资料的母本（flow-03 junction）
- `D:\GitHub\Flow-Tools`：号池生图网关（8001 端口），有同区漂移自动重锁 / 跨国熔断逻辑，与置信度引擎互补（它管单次生图前置安检，引擎管长期时序）
- `D:\GitHub\GLM-4flash`：本地轻量决策引擎，将承担「迁移建议 + 审批闸门」角色
- Antigravity Tools：7 账号粘性绑定（只读），配置在 `C:\Users\1\.antigravity_tools\`
