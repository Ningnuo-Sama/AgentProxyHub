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
- 2026-10-02 渠道策略进一步明确：优先沿用当前 Gemini 反代、Flow 反代、中转站和官方账号，不替换正在使用的渠道；金库中的新凭据由 Agent 自动比对、识别、健康检查，成功后才候选化，不要求用户逐项审批。CLIProxyAPI 暂缓纳管；root 微信不纳入当前 Hermes/iLink 通道。脱敏渠道状态记录保存在 `D:\ProgramData\AgentProxyHub\credentials\vault\channel_status.json`。
- 2026-10-01 用户拍板 Agent 全自动化方向：长期凭据金库为必选后台但可由检修开关关闭；允许 Agent 自动换绑、自动调用 Hermes A 方案微信告警；Gemini 与 GLM 权限等同，均可用于排障判定和审核；所有模型/渠道检查允许执行；CLIProxyAPI 纳入后续渠道纳管；调试能力集中到检修/调试面板，主面板以展示为主。凭据资料已用 Windows DPAPI CurrentUser 加密归档到 `D:\ProgramData\AgentProxyHub\credentials\vault`，未把明文写入 Git。提交 `10db8db`、`ffdb00c`。
- 2026-09-29 迁移完成（提交 `de5081e`）：`core/gen-config.ps1` 建池引擎落地并反转 `sync_nodes.py` 为自有建池维护（`--rebuild` 触发重建）；面板以蜂窝 1804 行成熟双视图版为底并入场景靶场与批量导出，**按用户决定移除四国 i18n，界面纯中文**。已部署 `D:\Program Files\AgentProxyHub` 并完成运行数据迁移；内核切至本项目 `bin\mihomo.exe`（geosite/geoip 需同时存在于运行根目录）；开机自启快捷方式由「蜂窝出口桥接」换为「AgentProxyHub」；旧蜂窝面板进程已退出。端口段 21001-21080 / 22001-22045 未变，Antigravity 7 账号粘性绑定实测全部连通。验收：`Parser::ParseFile` 通过、125 端口池生成正确、7 绑定端口 curl 实测有出口、`mcp/test_mcp.py` 5/5 通过、面板实机启动 `logs\panel.log` 正常。**FengWoBridge 自此退役**：`D:\Program Files\FengWoBridge` 目录整体原样保留作回滚，上游「蜂窝加速器」客户端（`FengWo` 进程）仍需保持运行作为出口上游，不属于退役对象。

## 2026-10-02 个人 TUN 接入准备（未上线）

- 原按钮文案是 `出海介入` / `出海展開中`；`停止內核` / `啟動內核` 为独立人工急停。
- 更正旧说明：固定125个SOCKS监听器绑定具体节点，rule模式切GLOBAL不会改变这些端口或MATCH规则。不得用GLOBAL冒充系统代理开关。
- EVA原停止调用health而不是真停止；源码现补定向急停接口和人工闩锁。恢复入口检查闩锁并抑制已存活内核重复启动；尚未演练停掉现役业务。
- 新增个人PERSONAL组与默认关闭TUN候选，125固定映射不变。真实内核 `-t` 校验通过。
- 续轮1新增 `core/tun_watchdog.py` 本地故障判定：连续3次DNS/直连/本机服务异常才触发一次撤销回调，人工急停优先且不自动重启，单独海外代理失败不急停全部业务；5项新增测试通过，全套42项通过。当前仅判定模块，不是已部署常驻watchdog，探针与撤销执行器尚待接入。
- 续轮2新增 `core/tun_controller.py` 真实控制器状态与仅撤销TUN执行器：显式禁用环境代理，凭据只读运行配置；不会停业务内核或改固定端口。现役读回TUN关闭，撤销返回already_disabled且未发送PATCH。新增4项测试，全套46项通过；常驻守护/真实开启仍未部署。
- 续轮3新增 `tools/tun_watchdog_runner.py` 独立入口，有限DNS子进程探测、公网TCP与上线前可用本地服务检查，输出脱敏决策；`--once`实测现役TUN关闭、不重启内核。未安装成服务/计划任务；控制器失联导致TUN状态未知时仅报告监护降级，仍须管理员侧撤销路由后备路径，不能当作已完备保命闭环。
- 续轮4已重新核实：当前会话为 Windows `High Mandatory Level`，APH mihomo PID 56072 正常运行；TUN 实际仍关闭。一次控制器 PATCH 返回204但读回仍为 false，已停止重复尝试，不能把204当上线证据。
- 已生成 `D:\ProgramData\AgentProxyHub\candidates\personal-tun-active-20261002.yaml` 并用正式 mihomo `-t` 校验通过；未启动候选，避免第二内核抢占21909/固定端口。
- 系统未检测到 Mihomo/Clash/Wintun TUN 网卡或198.18/默认路由变化；WLAN仍正常，UDP基线181个。真实上线剩余：通过受控入口加载候选/完整配置并验收DNS、国内直连、海外代理、本机服务和急停回滚。
- 当前无已验证APH特权服务。不借FlClash服务绕权限；watchdog runner尚未安装为服务，Steam动态省流/镜像下载尚未实现。代码准备不等于上线。
- 新代码回退标签 `pre-personal-tun-20261002`；运行配置、外置EVA页面、路由/DNS/系统代理快照位于 `D:\ProgramData\AgentProxyHub\backups\pre-personal-tun-20261002`。候选配置只存ProgramData，不进Git。
- 修正适配层曾硬编码控制密钥：现从运行YAML读取。历史Git已有该密钥，需后续协调轮换，不能声称历史凭据已清除。

## 回滚点

| 时间 | 仓库 | 提交 |
| --- | --- | --- |
| 2026-09-29 迁移前 | FengWoBridge | `local/custom` `193f000` |
| 2026-09-29 迁移前 | AgentProxyHub | `main` `12b15b8` |
| 2026-09-29 迁移完成 | AgentProxyHub | `main` `de5081e` |

运行数据回滚：`D:\Program Files\FengWoBridge\backups\20260929-134805-pre-agentproxyhub-migration`（迁移前）与 `D:\Program Files\FengWoBridge\backups\20260929-final-pre-retirement`（退役前全量快照）。回滚方式：停掉本项目 mihomo → 恢复蜂窝目录（未动过则直接 `启动桥接.bat`）→ 把自启快捷方式换回 `蜂窝出口桥接.lnk`。
