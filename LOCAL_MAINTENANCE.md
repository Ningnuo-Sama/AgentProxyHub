# 本地维护说明

- 源码仓库：`D:\GitHub\AgentProxyHub`，本地分支 `main`（自研项目，无上游）。
- 正式运行副本：`D:\Program Files\AgentProxyHub` —— **迁移目标，当前尚未部署**。
- 远端：`ningnuo-dot/AgentProxyHub`（已发布 v1.0.0 及绿色便携包，改动后需重建 release 才对外生效）。

## 数据边界（严禁入 Git）

`config/config.yaml`、`data/nodes.json`、`data/bindings.json`、`bin/mihomo.exe`、`bin/*.metadb`、`logs/`、`release/*.zip` 只属于运行目录。其中订阅链接与控制密钥属敏感信息。

## 与前身 FengWoBridge 的关系（2026-09-29 起）

本项目的通用化重构源自 `D:\GitHub\FengWoBridge`（前身「蜂窝出口面板」）。**但截至目前，所有成熟能力都还长在前身里，本项目只有一个 577 行的初版面板且从未部署过。**

- 现役运行时：`D:\Program Files\FengWoBridge`（mihomo 内核 + 125 端口 21001-22045 + 1804 行成熟面板 + 巡检引擎）
- 本项目现状：`ui/panel.ps1` 577 行初版（有四国 i18n / 场景靶场 / 批量导出，但缺成熟分级分组与巡检风控）
- `core/sync_nodes.py` 当前设计写的是「**不重复建设端口池**，只从蜂窝同步测绘」——这是"本项目作为消费方"的设计，与迁移方向相反，迁移时需反转。
- `启动AgentProxyHub.bat` 在缺 `bin\mihomo.exe` 时会从 `D:\Program Files\FengWoBridge` 借用内核，同样体现"骑在前身上"的现状。

## 硬约束

- 端口段 `21001-21080`（蜂窝）/ `22001-22045`（星辰）**迁移后保持不变**。Antigravity Tools 的 7 个账号粘性绑定直接写死这些端口，改段即全部失效并触发 IP 漂移风控。`config/config.example.yaml` 里的 `20001/30001` 是通用模板值，本机部署不采用。
- `data/bindings.json` 是「环境 → 端口」锁定账本，由本项目 MCP 与 `D:\GitHub\CloakMulti` 的 `cloakmulti/aphub.py` **共写**，改格式必须两边同步。它与 Antigravity 的账号粘性（`C:\Users\1\.antigravity_tools\gui_config.json` 的 `account_bindings`）是两回事，不要混用。
- MCP 工具表由宿主启动时固化，改 `mcp/server.py` 后必须重启 Agent 客户端才生效。

## 验证方式

- PowerShell 脚本：`Parser::ParseFile` 语法解析 + 实机启动后看 `logs\panel.log`。
- Python：`python -m py_compile` + `python mcp/test_mcp.py`（5 项端到端）。
- 面板：UI 自动化点击关键按钮，再用 `SHGetFileInfo` / 截图 / 日志断言结果。
- 网络：`curl.exe --socks5-hostname 127.0.0.1:<port>` 实测出口，不能只看 `data/nodes.json` 的评分。

## 变更记录

- 2026-09-29 补建 `AGENTS.md` 与本文件：此前本仓库没有任何维护脚手架，也在 `main` 上直接提交。
- 2026-09-29 MCP 状态可信度修复（提交 `12b15b8`）：`list_matched_proxies` 原先只读测绘快照、完全不看本地内核是否在跑，导致内核已死、127 个端口全部拒绝连接时仍返回 22 个 S/A 级"可用"出口。现补上 `port_open` 真实 TCP 预检、`snapshot.age_hours` 快照年龄、`local_exit` 运行态块与 `warning`；`get_profile_bindings` 增加只读的 Antigravity 账号粘性，并写明两套账本语义不同。
- 2026-09-29 迁移启动（进行中）：用户确认「AgentProxyHub 完整部署并取代蜂窝」，面板以蜂窝成熟版为底并入本项目 i18n 与场景靶场。安全网已建：`D:\Program Files\FengWoBridge\backups\20260929-134805-pre-agentproxyhub-migration`，内含 `config.yaml`/`nodes.json`/`gui_config.json` 等运行数据与 `MIGRATION-STATE.md` 状态快照。

## 回滚点

| 时间 | 仓库 | 提交 |
| --- | --- | --- |
| 2026-09-29 迁移前 | FengWoBridge | `local/custom` `193f000` |
| 2026-09-29 迁移前 | AgentProxyHub | `main` `12b15b8` |

运行数据回滚：`D:\Program Files\FengWoBridge\backups\20260929-134805-pre-agentproxyhub-migration`。迁移期间前身运行副本保持原样不动，直到本项目通过验收。

## 2026-10-13 代理漂移事故根因修复（Agent 执行，跨 Flow-Tools 对齐）

现象：Flow-Tools 号池账号被熔断，报「代理出口跨大区漂移」——21013/21007 出口 Ukraine、22003/22008 出口 Macao，而 bindings.json 承诺 US。

根因（均在本仓库内）：
1. `confidence_engine.update_record()` 漂移判定按 **IP**（`current_ip != baseline_ip`），同 IP 被 Google 改判国别时判为零漂移 → 隐形漂移。
2. 自动换绑触发条件仅「送中/离线」，**非锁区跨洲漂移（US→UA）永不触发**。
3. `get_protected_bound_ports()` / `select_ports()` / `run()` 三处读 `v.get("port")`，而 bindings.json 端口是 **JSON 键** → 保护集为空。
4. 审计 `repair_events.jsonl` 2026-10-10 曾 `heal_success` 到 `xc-22027`（Ukraine）并放行 → 漂移由自愈自己造成。
5. `AgentProxyHub-account-guard` 计划任务被禁用。
6. `nodes.json`（10-04）陈旧 `isSentToChina` 导致 22002/22003/22008 被假判送中。

已修：
- `core/hot_swap_executor.py`：`get_protected_bound_ports()` 改按 JSON 键解析（回退 `port` 字段）；`scan_and_heal_all()` 增加 `cross_continent`/`cross_country_same_region` 触发分支（`select_candidate_node` 跨大区拒绝逻辑保持不变）。
- `core/confidence_engine.py`：新增 `load_bound_ports()` 并按键解析（`select_ports`/`run` 复用）；漂移触发改为「IP 或 Google 判国变化」；吸收基线收紧为仅 `same_country`；自愈触发扩展（送中/离线语义不变）；`auto_heal_port` 导入补 `except ImportError` 双形态（修脚本直跑崩溃）。
- 数据：`bindings.json` 补登 21007/22003/22008；`nodes.json` 以实测定点修正 7 条陈旧「送中/中国」元数据；`confidence_state.json` 清理 21013/21007/22003/22008 陈旧基线（曾为 CHINA）与假否决。
- 任务：`AgentProxyHub-account-guard` 已 `/ENABLE`。
- 端口修复（走 `hot_swap_executor.py --port --proxy`，含热重载+失败回滚）：21013→fw-21012、21007→fw-21014、22003→fw-21003、22008→fw-21003；实测 7 端口 Google 判国全 US。

备份：`backups/{hot_swap_executor,confidence_engine}.py.bak-20261013-043123`、`backups/confidence_engine.py.bak-*-boundparse`、`backups/nodes.json.bak-*-meta`、`backups/confidence_state.json.bak-*-align|*-meta`、`backups/bindings.json.bak-*-align`、`backups/config.yaml.bak-20261013-04*`。
源码镜像 `D:\GitHub\AgentProxyHub` 已同步同两份 .py（未 commit）。

遗留（未闭环）：
- 测绘源（`data/port_map.csv`、`config/bridge.json`、`data/upstream_nodes.json`，均 10-01）陈旧，且**无任何调度执行 `core/sync_nodes.py`** → 本轮定点修正属「实测覆盖陈旧值」，后续手工 sync 可能回退；根治需把测绘刷新纳入计划任务。
- `nodes.json` 的 `isSentToChina` 仍被 `confidence_engine` 用作否决输入之一（本轮已定点修正，根因未除）。
- 真实漂移未处理：21022（Bahrain）、22010（Singapore）。

### 2026-10-13 追加：测绘源刷新链路修复（订阅 API 失效 → 本地清单兜底）

现象：`data/upstream_nodes.json`、`port_map.csv`、`config/bridge.json` 长期停在 2026-10-01；手工刷新 `refresh_sources` 两个源都 `ok:false`（provider_a URLError / provider_b HTTPError），只能保留 last-known-good。

根因（三处）：
1. **订阅 API 鉴权被拒**：两个源 `fetch_endpoint` 带 token 仍返回 **HTTP 403**（非地域问题——所有出口都 403，无鉴权时也是 403）。
2. **本地清单兜底形同虚设**：`core/upstream_fetcher.py` 的 `profile_fallback` 只在「请求成功但内容为空」时生效，**请求失败直接抛错**，永远走不到兜底。
3. **星辰采集脚本落盘路径错位**：`data/refresh-xingchen-profile.ps1` 的 `$dst` 指向**源码仓** `D:\GitHub\AgentProxyHub\data\xingchen_profile.yaml`，而运行时实际读取的是**部署副本** `D:\Program Files\AgentProxyHub\config\xingchen_profile.yaml` → 每日任务 `AgentProxyHub-xingchen-profile-refresh`（Clash UA，上次 rc=0）"成功"却写到没人读的地方。

已修：
- `core/upstream_fetcher.py`：把请求包进 try/except；**请求失败时若登记了 `profile_fallback` 就回落到本地清单**（否则原样抛出，失败语义不变）。
- `data/refresh-xingchen-profile.ps1`：`$dst` 改为**部署副本**运行时路径，`$mirror` 留档源码仓；写入改为**原子替换**（staging + Move）；保留 `.bak-<时间戳>`；保持体积>20000 且节点数>30 的**双门禁**与「未过门禁保留上一版并非零退出」；**全文件改为纯 ASCII**（控制通道编码红线，中文注释曾导致 PS 解析报 MissingCatchOrFinally）。
- 刷新成功：蜂窝 86 + 星辰 48 = **134 节点**（星辰为订阅直取，Clash UA `clash-verge/*`；无 UA 会 406）；`sync_nodes.py` 重衍 125 端口 / 存活 92。

未做（按经验红线刻意不做）：**未执行 `gen-config.ps1` 端口池重建/重载**，避免打断存量账号长连接与端口粘性绑定。

遗留：`nodes.json` 的 `googleCountry` 标注仍非实测（实测 21017=Colombia、21051=Ukraine、21070=Bahrain，元数据却标 US），需把国别测绘做成实测来源才能根治。

## 2026-10-15 换蜂窝新账号后的流量治理（Agent 执行）

现象：用户更换蜂窝账号（新订阅 Vip4-300GB，86 节点，入口域名 `base88.0098.fun`）后反馈流量消耗过快，要求只保留反代与显式绑定对象接入网关。

根因（按实测贡献排序）：

| 排名 | 流量来源 | 实测数据 |
| :--- | :--- | :--- |
| 1 | AUTO-POOL url-test 全量轮询 | 124 个成员 × 每 180 秒一轮 `generate_204`，失败重试叠加，今日日志 631 行里 571 行是 `policies.google.com` 判国探测 |
| 2 | 旧账号残留节点被反复重连 | 新订阅只保留 4 个 fw 节点，config.yaml 却仍有 75 个指向 `vip88.0098.fun` 等旧入口的定义，121.14.13.199 / 18.167.36.222 持续 refused |
| 3 | Antigravity 7 个 Google 账号 | `daily-cloudcode-pa.googleapis.com` 长连接，120 秒实测下载 17.4 MB（145 KB/s），这是业务刚需不属浪费 |
| 4 | 未登记端口 22039 | `pythonw` 长连接，bindings.json 未登记，用途不明 |

治理动作：

1. **关停账号判国探测**：计划任务 `AgentProxyHub-account-guard` 已 `/DISABLE`，`autonomy_state.json` 的 `auto_rebind_enabled` 置 `false`。用户明确「里面住着的 Agent 没什么用，后面自己重修」，故不保留自动换绑。
2. **AUTO-POOL 瘦身**：成员 124 → 4，节奏 180s → 1800s。保留 `proxies:` 里的全部节点定义（否则 listener 悬空），只修剪 group 成员。
3. **生成器同步**（`core/gen-config.ps1`）：新增参数 `-AutoPoolInterval`（默认 1800，原硬编码 180）与 `-AutoPoolProbeNodes`（白名单，逗号分隔节点名；为空则退化为全量，保持历史行为）。`groupLines` 继续全量喂 ALL 组，另有 `probeLines` 只含白名单喂 AUTO-POOL。ALL 组增补 `DIRECT` / `REJECT` / `AUTO-POOL` 三项。输出行新增探测节点数与节奏。

踩坑（重要，后续易再犯）：

- **不要直接删 proxy 定义来阻止探测**。删除 fw 节点定义会让指向它的 listener 悬空，实测被删端口（21003/21007/21012/21013/21015/22003/22008）全部 HTTP 000。正确做法是保留定义、只修剪 group 成员——mihomo 的 listener 直连 proxy，节点只需存在于 `proxies:` 即可服务流量。
- **重建脚本丢尾部**。手写重建逻辑时 ALL 组、GLOBAL 与整个 `rules:` 段被丢弃，YAML 校验在 `d["rules"]` 处 KeyError。今后改运行副本务必用 Python `yaml.safe_load` 做结构化断言，不能只 grep 关键字。
- **`put` / configs?force=true 的 JSON 路径**。backslash 在 JSON 字符串里必须转义，`curl --data-raw "{\"path\":\"D:\\\\Program Files\\\\...\"}"` 可重载；单反斜杠一律 `400 {"message":"Body invalid"}`。
- **`.ps1` 落盘 BOM**。用编辑工具改 `core/gen-config.ps1` 后 UTF-8 BOM 被剥掉，PowerShell 5.1 按 ANSI 解析导致 here-string 内 `$($listenerLines -join ...)` 后的 `- https://...` 出现 `Unexpected token`。所有面向 PowerShell 的 `.ps1` 必须是 UTF-8 带 BOM。

效果（180 秒实测对比）：

| 指标 | 治理前 | 治理后 |
| :--- | :--- | :--- |
| 下载 | 17.4 MB / 120s（约 17 GB/天） | 0.11 MB / 180s（约 53 MB/天） |
| 内核后台探测 | 多路 `policies.google.com` 滚动重试 | 连接数为 0，bridge.log 120 秒增量 0 字节 |

当前运行态：mihomo PID 17808 未重启（重载后已运行 5h+），250 个监听端口齐全，10 个业务端口 Google 判国 HTTP 200。回滚点 `backups\traffic-opt-20261015-053321\`（原始 config.yaml / bindings.json / nodes.json）与同目录下 `config.yaml.bak-trafficopt-*` / `.bak-restore-*` / `.bak-append-*` / `.bak-tailfix-*`。

回滚命令（确认后再执行）：

```
curl.exe -X PUT -H "Authorization: Bearer <secret>" `
  -H "Content-Type: application/json" `
  --data-raw "{\"path\":\"D:\\Program Files\\AgentProxyHub\\backups\\traffic-opt-20261015-053321\\config_config.yaml\"}" `
  "http://127.0.0.1:21909/configs?force=true"
```

未做：`data/nodes.json` 仍是 10-14 的 125 端口快照，与治理后的 4 + 45 配置不同步；用户后续重修判国逻辑时应一并重衍。重修方向见 `docs/judge-country-recheck-plan.md`（结论：改为事件驱动，不要恢复定时全量轮询）。`scratch/traffic_opt_config.py`、`restore_defs_prune_groups.py`、`restore_rules_tail.py`、`relisten_listeners.py` 是本次一次性脚本，已记录方法但不要当长期工具复用。
