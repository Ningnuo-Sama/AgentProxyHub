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

## 2026-10-02 管理员续接实测

- 当前宿主High权限，但旧mihomo对TUN PATCH实际报 `configure tun interface: Access is denied`，不以宿主权限当作旧内核权限证据；TUN未上线。
- 尝试候选启动时PowerShell Start-Process数组参数中的空格未保留引号，导致内核未监听。已停止错误启动实例，用完整引号参数恢复正式配置。
- 恢复后PID26700，21909监听正常；125固定SOCKS端口逐一TCP连接全部成功，真实控制器读回TUN关闭。期间业务连接会中断，不声称无影响。
- 尚未验证Google/百度实际分流、UDP、看门狗断网闭环和按钮运行部署；后续不得重复无效启用操作，需要先核对新内核权限和守护部署。
- 续轮4修复监护判定：控制器失联None保持unknown而非误报tun_off；DNS子进程超时转失败样本而不退出守护。新增3项回归测试，全套49项通过；本轮读回TUN关闭、125端口全通。unknown目前只告警，独立失联撤销后备尚未完成，仍禁止把此看门狗称作上线保护闭环。

- 续轮5新增关闭TUN快照热重载执行器及路径/业务映射检查。真实演练收到HTTP400：mihomo SAFE_PATHS仅允许运行根目录，拒绝ProgramData快照；未绕过此保护，也未把失败说成回滚成功。应由后续正规部署流程将已核对关闭快照发布到运行根允许目录，再演练。
- 续轮6审计确认不放宽SAFE_PATHS、不在普通adapter复制含密钥配置到Program Files；应由受控特权服务完成ACL、原子复制、哈希/disabled/125映射校验后再调用PUT。当前未实现该特权服务，故不宣称回滚闭环。
- 安全审查提交417b822修复adapter同进程start/stop串行、拒绝空/null Origin的core写操作、启动失败重新置人工闩锁；不是跨进程锁，也不是用户认证。全套测试新增到50项，真实TUN仍关闭。

- 续轮7在High会话中新增 `tools/prepare_runtime_rollback.py`：对ProgramData关闭TUN快照做disabled/125 listener映射校验、SHA-256记录、临时文件原子替换到运行目录。运行目录快照PUT热重载实测成功，读回TUN=false。
- 隔离候选再次启动实测出现 `Meta` 网卡，但无198.18/分流路由可证；没有把网卡存在当成完整上线。已停止候选并恢复正式配置，21909正常，125固定端口全部TCP通过，live TUN=false。
- 候选进程参数与现役进程短时重叠，暴露单实例启动门禁仍需加强；后续必须先确认旧进程退出和21909释放，再启动候选。

- 续轮8为恢复入口增加自有mihomo单实例门禁：若已存在同路径owned进程则拒绝再次拉起；恢复runner仅允许已知APH入口名。新增回归测试，当前全套51项通过。注意该检查仍是恢复入口级门禁，不是跨进程原子锁；正式候选切换仍需先停止旧实例并确认21909释放。

- 续轮9首次完成单实例候选切换实测：先确认旧实例退出，再以候选启动；Meta网卡出现，198.18.0.0/30及全局分流路由出现，live controller读回 `tun=true`。百度HTTP 200；Google HTTPS在8秒内握手超时，不能声称海外链路可用；125固定端口全通。
- 随后使用运行目录 `rollback-disabled.yaml` PUT热重载，读回 `tun=false`；Meta网卡/路由消失，125固定端口全通，21909继续监听。再加载正式 `config.yaml` 复核关闭状态仍为false。完成一次可逆的TUN开→关演练，但Google代理、UDP/Steam、DNS劫持和常驻看门狗仍未验收。

- 续轮10看门狗runner新增启动前manual-halt短路：人工急停时直接输出respect_manual_halt并退出，不探测、不调用撤销、不复活内核；新增测试后全套52项通过。正式状态仍TUN关闭。

- 续轮11新增只读验收工具 `tools/verify_tun_runtime.py`：同时读控制器、Meta网卡、198.18/路由、125端口及百度/Google；在正式TUN关闭时正确返回 `not_verified`/退出码2，实测百度200、Google超时、125端口全通。该工具不改配置、不启停内核。

- 续轮12修正EVA出海按钮：请求不再发送误导性的 `GLOBAL` 参数；`/api/route` 被后端拒绝时不再本地伪造切换成功，原文案保持不变并写入失败日志。外置页面改动尚未部署到正式静态服务，需刷新/部署后生效。

- 续轮13补充看门狗海外HTTPS代理探针，将 `proxy_ok` 从固定True改为实际有限探测；探针失败作为证据输入，但仍不会因单个海外节点失败直接急停。新增测试后全套53项通过。

- 续轮14收紧只读验收：`tun_verified` 现在必须同时满足TUN控制器、Meta网卡、分流路由、125固定端口、百度国内直连和Google海外HTTPS；任一失败返回not_verified。正式TUN关闭时实测退出码2，未隐藏海外超时。

- 续轮15最终门禁复核：全套53项测试通过；只读验收返回not_verified/退出码2（TUN关闭、百度200、Google超时、Meta/路由无、125端口全通）。因此本目标在当前12轮内未达到全量上线条件，不标记完成；代码、候选、回退与实测边界已保留。

- 续轮16在用户确认管理员会话后复核：`whoami /groups`为High；单实例直接启动候选时Meta网卡、198.18/分流路由、控制器`tun=true`和125端口均出现/正常，但Google HTTPS仍超时，严格验收仍为not_verified/退出码2。随后运行目录关闭快照热重载成功，TUN=false、Meta消失、125端口全通。正式状态已回退，未完成全量上线。
- 续轮17再次发现正式内核曾意外退出，已恢复后再做单实例候选切换；结果与续轮16一致：TUN结构和125端口正常，Google超时。未换绑节点；随后已恢复正式配置，当前TUN关闭、125端口全通。

- 续轮18对可用美国出口做只读/有限验证：MCP实测21012与21014 SOCKS5到Google:443均verified，延迟约0–1ms；当前AUTO-POOL活动为fw-21001。候选TUN启动后Meta/TUN=true、百度200，但系统HTTPS Google仍超时；尝试控制器切PERSONAL到21012返回HTTP400，未强行改组或换绑。已安全回退TUN=false、125端口全通。结论：节点局部SOCKS可通不等于系统TUN流量可用，仍需核查DNS/HTTPS路径和PERSONAL组配置后再上线。

- 续轮19修复恢复通知遗漏：将Hermes/鲸管家通知移入 `ResidentEngineer.recover_mihomo()` 的统一成功出口，MCP包装层改为复用结果，避免PowerShell/其他本地调用恢复成功却不通知或重复通知。新增回归测试，全套54项通过；未实际触发恢复/通知，不声称Hermes已送达。

- 续轮20实测通知链路：`notify_all` 返回 `hermes_weixin=true`、Hermes CLI returncode 0/status sent；鲸管家本次超时返回false。该实测使用固定去重event_id且不含凭据；证明Hermes发送通道可用，但不等同于已触发一次真实内核恢复通知。

- 续轮21生成固定PERSONAL=fw-21012（MCP先前实测该SOCKS到Google:443 verified）的TUN候选，正式mihomo `-t`通过；启用后Meta/198.18/分流路由/tun=true/125端口均正常，但Google HTTPS仍超时。Cloudflare HTTPS可达（200），说明不是所有海外TLS均失败；Google域名解析结果漂移，仍需专门DNS/Google路径诊断。已回退关闭TUN，125端口全通，未改绑定。

- 2026-10-03 DNS差异诊断：新增只读 `tools/google_dns_diagnostic.py`，精确传curl参数、禁用环境代理，21012完整TLS+Google204连续两次成功（远端域名解析）；同端口本机DNS解析模式连续两次TLS超时。证明DNS解析路径差异是当前Google失败的具体候选根因，不再把SOCKS握手称作HTTPS验证。未改配置/重启内核，live TUN=false；全套54测试通过。

- 续轮22针对已证实DNS差异，在PERSONAL候选中加入fake-ip、国内过滤、DoH nameserver/proxy-server-nameserver及fallback；正式mihomo `-t`通过，全套54测试通过。仅写入ProgramData候选，未加载现役，需下一轮单实例实测Google并回退。

- 2026-10-03最终续轮：为隔离21012候选补齐`dns-hijack: [any:53]`、gvisor和198.18地址，修正fake-ip-filter为`+.cn`；启动后严格验收首次返回 `tun_verified`/exit 0（百度200、Google204、Meta Up、分流路由、125端口全通），系统Google DNS返回198.18.0.12。finally中热重载关闭快照成功，随后确认tun=false、Meta网卡/路由数量均0、125端口全通。预检PowerShell读取不存在halt文件出现非终止错误；已核实统一is_halted为false（缺失表示未急停），后续必须用统一门禁而非裸Get-Content。源码补齐DNS劫持及回归断言，未部署正式常驻配置，UDP/Steam/独立watchdog/跨进程急停及失联回滚仍待完成。

- 2026-10-03业务无干扰隔离改造第一步：新增`core/personal_tun_isolation.py`，独立个人候选默认TUN关闭、控制器21919带随机鉴权、设备APH-Personal、198.19地址，仅经loopback固定SOCKS21012出海，不复制125业务listeners或节点凭据，拒绝业务TUN开启/无物理接口/端口冲突。56测试通过，实际mihomo -t通过。仅生成ProgramData关闭候选，未启动第二内核、未停止业务内核；进程级防回捕、独立目录/急停/watchdog和Gemini长连接无干扰仍未验证。此前恢复通知移动到底层仍无法覆盖任意PowerShell直接启动，不能把它描述为已消除所有漏报。

- 双内核隔离第二步：新增只读personal_tun_preflight门禁，人工急停优先，业务TUN未知或开启拒绝，个人可执行路径与业务相同拒绝，独立急停未安装拒绝，额外listeners和控制器冲突拒绝；返回明确不等于防环/Gemini无干扰验收。全套60测试通过。未安装/启动个人进程，需下一步实现总急停覆盖及独立生命周期。

- 双内核隔离第三步：源码kernel_control增加个人路径白名单与stop_personal_kernel，只停个人路径、不置人工总闩锁、不修改系统代理；emergency_stop先设闩锁再精确停止业务及个人两个路径。新增模拟回归，全套63测试通过；未调用真实急停、未部署运行适配器、未安装个人可执行副本，跨进程锁与业务无干扰仍未验收。live业务TUN=false。

- 双内核隔离第四步：control_lock切换为可重入Windows一字节文件锁，等待超时拒绝，真实子进程测试确认持锁时竞争退出7、释放后成功；全套65测试通过。仅使用同一协议的入口受保护，直接PowerShell/尚未接入的恢复和watchdog不受保护；未部署运行副本，不能宣称全系统跨进程协调完成。

- 扩展授权后协调修复：恢复入口和TunController非GET写操作接入共用文件锁；个人exe预检收紧为总急停覆盖的固定路径；急停先用唯一临时文件原子发布闩锁再等待控制锁，恢复Popen前再次检查。66测试通过，未部署/切断业务。独立看门狗仍须指向21919，防回捕和Gemini无干扰未完成；锁等待与人工启动清闩锁竞态仍需完整审查。

- 审查闭环：EVA stop分支移到外层control_lock之前，急停可以立即发布闩锁；文件锁总deadline含同进程RLock等待，新增真实线程竞争超时测试。67测试通过；未部署EVA、未真实急停，个人watchdog和防回捕仍待完成。

- 个人监护入口：runner新增--personal固定读取个人config/21919，网络故障与连续三次控制器失联仅调用个人停止，人工闩锁短路、不启动/复活，独立失联防抖单次回调测试。70测试通过；默认--once实测业务tun_off。未安装个人配置/看门狗任务、未真实失联演练；个人停止后的路由/DNS撤销仍待验证，不能称保护服务已部署。

- 独立个人关闭实例实测：安装personal目录同版本mihomo（SHA256与业务相同）及独立geo资源/config，-t通过；TUN=false启动个人21919，个人和业务控制器均正常；调用源码stop_personal_kernel后仅个人控制器消失，业务PID20788/创建时间01:14:05保持不变、业务TUN=false、125端口全通。--personal --once正确报告unknown、不误停业务。70测试通过。未开个人TUN、未部署EVA/常驻任务、未验防回捕及Gemini请求；安装副本仅关闭候选，安全退出能力是源码工具实测，不代表旧EVA已覆盖。

- 业务上游防回捕清单：新增business_route_exclusions，有界TUN关闭现场解析7个业务server，均成功，形成9个精确/32或/128个人路由排除及上游域名fake-ip过滤；缺失解析/fake-IP拒绝。72测试及独立mihomo -t通过。仅生成关闭候选，未修改业务节点/绑定、未开TUN；端点变化必须刷新，现有连接远端IP、DoH端点、实时物理选路仍需覆盖，不把排除清单等同运行防环证明。

- 防回捕覆盖补充：现场业务既有公网连接43.207.231.45与DoH 120.53.53.53，Find-NetRoute均为WLAN index9、网卡Up，业务TUN=false；源码清单扩展业务DoH/DoT endpoint及active_addresses，DNS域名解析缺失仍拒绝，localhost过滤保留。73测试通过；未生成新部署配置/开启TUN，开启后的真实选路尚未验证。

- 双内核TUN首次受控实测：verify_isolated_tun有界刷新节点/DNS/既有连接，共12排除地址；个人开启TUN时系统Google204与显式21012远端解析Google204均成功，各现场端点Find-NetRoute保持WLAN；finally仅停止个人，个人网卡/路由均0，业务PID20788及创建时间不变、125端口全通、业务TUN=false。初次JSON单元素类型导致启动前拒绝，修复后完成演练。73回归通过。随后收紧工具退出判据并py_compile通过，未重跑改后版本；非全账号/UDP/Gemini流式/抓包验收，不能声称全量无干扰。

- 双内核复验：演练配置改唯一文件名、增既有连接身份统计，收紧双HTTPS/物理路由/个人撤销退出门禁版本真实返回0；业务PID不变、个人网卡/路由0、系统及21012 Google204成功。35条既有连接开启期间保持32、退出后保持9，可能自然结束但未证明，不能据exit0声称长连接/Gemini无干扰。追加明确gemini_noninterference_verified=false及全连接保持布尔，py_compile/73测试通过（追加标识未再实跑）；业务TUN=false。

- 持续连接实测：新增无重连PersistentProbe，经21012同一SOCKS+TLS socket在个人TUN开启前/期间/退出后均Google204、same_socket=true、服务器未要求关闭；收紧演练判据真实exit0。业务PID不变、上游WLAN、个人路由/网卡0；既有11条连接保持10条，不能断言其他连接为何结束。73回归通过，业务TUN=false。仅证明21012受控keep-alive，不等于所有账号/Gemini SSE/UDP验收。

- 账号出口覆盖实测：现场账本为8个绑定端口（非历史7个）：21012/21022/22002/22010/22021/22023/22024/22038，TUN关闭基线与个人TUN开启期间全部完整TLS Google204；账号配置SHA256前后相同，未换绑。同21012持续socket开前/期间/退出后204、业务PID不变、上游WLAN、个人网卡/路由0，演练exit0。只验证出口，不含账号登录/模型生成/SSE；existing connections 24→23→16不判定自然结束原因。新增account_exit_baseline工具，不发付费请求。

- 个人controller-loss故障注入：演练运行个人TUN后，将测试监护客户端指向已bind但不listen的loopback端口，3次真实连接拒绝，第3次PersonalControllerGuard调用stop_personal成功；真实个人控制器随后不可达，网卡/路由0，业务PID不变，21012持续TLS退出后204，8账号出口开启期间204、绑定配置不变。演练exit0，随后增加故障注入验收判据仅py_compile+73回归，未重跑收紧版。不是生产控制器自然失联或常驻服务验收。

- 个人关闭意图持久化：新增personal_route_state，缺失/损坏默认off，close_personal在共用锁内先原子落盘off再只停个人，失败返回不隐藏；个人runner在off时不计失联、不重启，若读到TUN仍开则仅停止个人。75测试通过，--personal --once现场输出personal_desired_off。未接通EVA/启动入口、未安装常驻任务；控制器未知且off时的残余进程清理仍需生命周期完善。

- 生命周期入口补齐：新增personal_lifecycle，start/stop/status仅面向独立个人内核；start遇人工急停返回停止內核，日常stop先持久化desired_on=false再个人停止，status同时报告控制器/意图/进程，EVA /api/route按action接入并保留出海介入/出海展開中及停止內核标签语义。78测试、py_compile和diff检查通过；源码现场desired_on=false、个人进程不存在、业务TUN=false。正式EVA服务尚未重启加载源码，个人关闭配置不是可用生产TUN配置，不能声称按钮已上线。

- EVA源码适配层本轮隔离验证：启动源码tools/eva_h5_adapter.py临时监听8767（未重启任何现役mcp/业务mihomo），POST /api/route status返回个人controller未知、desired_on=false、process_running=false；POST stop返回ok=true、business_kernel_changed=false、label=出海介入；业务控制器仍tun=false。临时进程随后已停止。运行副本tools/eva_h5_adapter.py不存在/未部署，故不声称正式EVA已更新。

- EVA前端动作已修正为向后端发送action=start/stop，不再发送旧mode=overseas/direct；仍保留文案出海介入/出海展開中。个人生命周期增加生产配置门禁：正式personal/config.yaml当前tun.enable=false时拒绝start（现场返回personal_config_not_ready），避免按钮伪成功或误开关闭候选；79测试通过、diff check通过。EVA启动脚本仍指向源码适配层，未正式部署/重启。

- 个人开启候选安装：核对防回捕候选14条排除路由后，先将个人运行配置备份至personal/backups/config-disabled-20261003-022944.yaml，再写入同候选tun.enable=true；独立mihomo -t校验成功。未启动个人、desired_on仍false，看门狗--personal --once输出personal_desired_off；业务TUN=false、业务内核未重启。79测试通过。该配置含运行secret且在Program Files受控目录，不入Git；生产启动仍需单独生命周期/API验证与回退演练。

- 正式个人生命周期闭环实测：源码personal_lifecycle.start启动已安装TUN=true候选，4秒后控制器21919报告tun_enabled=true/process_running=true/desired_on=true；系统Google204与显式21012 Google204均成功；stop只停个人并返回出海介入，随后个人控制器不可达、进程不存在、desired_on=false；业务控制器始终tun=false、业务PID未重启、125固定端口全通。79测试通过。已恢复个人关闭状态。仍未部署常驻看门狗/EVA正式适配层，未做Gemini/SSE/UDP全量验收。

- 个人看门狗常驻入口：新增run-personal-watchdog.ps1/.bat及安装/卸载Scheduled Task脚本，任务名AgentProxyHub-Personal-TUN-Watchdog，AtLogOn、仅--personal --interval 5，不自动启动个人TUN。已实际Register并Start验证，任务启动个人runner且业务TUN=false；随后Stop任务，当前任务已安装但未运行（Ready）。runner直接受限测试超时是预期常驻行为，不是功能失败；卸载脚本可回退。79测试通过。

- EVA源码API二次实测未完成：直接启动时发现已有多个eva_h5_adapter候选进程/8767竞争，POST请求出现连接意外关闭及stop返回500；随后清点未发现仍监听8767的EVA适配层，个人desired_on=false/进程不存在，业务状态未受影响。未继续强杀不明宿主进程，也未把失败误判为个人TUN故障。正式入口仍需单实例管理和端口归属后再验收。

- EVA单实例包装器：新增run-eva-adapter.ps1/.bat，启动前先健康复用8767，非健康占用则拒绝，不杀未知进程；无占用时启动源码适配层并轮询health。EVA前端启动脚本已改指向包装器。现场验证adapter_started、重复启动existing_healthy_adapter_reused、/api/route status可用，随后停止验证进程；业务TUN=false。79测试通过。正式前端脚本已改源码路径但未重启用户前端。

- 最终运行态收口：已启动已安装的AgentProxyHub-Personal-TUN-Watchdog登录任务；当前个人desired_on=false，任务仅执行个人21919关闭态监护，不启动个人TUN；业务控制器tun=false，125固定端口探活全通。任务状态现场为Running；EVA8767未保持常驻（避免重复实例），业务mihomo未执行重启。79测试通过。任务可用uninstall-personal-watchdog-task.ps1回退。

- EVA最终单实例真实闭环：重启单实例包装器后，/api/route start仅在控制器21919回读tun_enabled=true后返回code=personal_started/出海展開中；随后stop返回ok、business_kernel_changed=false、出海介入。期间业务内核未重启，测试后个人desired_on=false、个人进程已停。此前旧适配层返回personal_start_submitted的竞态已修复；79测试通过。页面8768/适配层8767均可访问，但尚未做浏览器实际点击截图和Gemini/UDP全量业务验收。

- 浏览器真实验收完成：访问8768 EVA页面，按钮初始显示“出海介入”；真实点击后页面显示“出海展開中”，后端start返回personal_started且controller tun=true；再次点击后页面恢复“出海介入 / LINE: OFF”，stop成功。业务控制器始终tun=false，个人desired_on=false，79测试通过。未调用生成/付费接口。该闭环覆盖按钮及生命周期，但仍不覆盖Gemini真实SSE、UDP/QUIC和自然失联。

- 生产看门狗自然失联演练：个人TUN曾真实启动（PID21704、desired_on=true），随后仅强制终止个人可执行文件；20秒后业务PID/控制器仍正常、业务TUN=false，但发现旧逻辑不会把desired_on固化为false。已修复PersonalControllerGuard三次失联调用close_personal（先原子落盘off再个人停止），80测试通过；关闭意图已现场重置false，看门狗任务重启运行。该演练证明未复活个人且业务不受影响，也记录了修复前缺口；修复后尚未再做自然失联重复演练。

- 修复后自然失联复测：启动个人TUN返回personal_started/tun=true，单独终止个人进程，等待20秒（≥3个5秒看门狗采样）后desired_on=false、个人进程/控制器不存在；看门狗任务仍Running；业务tun=false、125固定端口全通。80测试及diff通过。修复后自然失联链路已闭环，未复活个人或重启业务。

- UDP/QUIC边界实测：清理个人test-active临时配置（送回收站），保留关闭快照config-disabled-20261003-022944.yaml。个人TUN启动/控制器tun=true成功；通过21012 SOCKS5 UDP ASSOCIATE返回127.0.0.1:21012，但向223.5.5.5:53发送标准DNS UDP请求6秒超时；finally独立stop成功、desired_on=false、业务tun=false、125端口全通。结论：当前固定SOCKS UDP链路尚未验收，不能宣称Steam/QUIC/UDP可用；未修改业务配置/绑定，未调用付费服务。

- UDP失败归因对照：同机直连223.5.5.5:53的标准DNS UDP请求成功收到31字节响应，固定SOCKS UDP ASSOCIATE虽成功但经21012转发同请求6秒超时；故当前失败定位为BUSINESS-SOCKS/业务节点UDP转发或协议封装未验收，不是本机公网DNS整体不可达。个人desired_on=false、业务tun=false，未再启动个人。

- EVA额度口径统一（不改UI结构）：以后端账号源quota_groups为唯一来源，新增/api/quota-summary并映射现有额度卡：Gemini/Claude均显示5H与weekly加权均值，生图显示gemini-3.1-flash-image账号模型均值；截图实测页面读取Gemini 55.1%（5H94.2%/7D55.1%）、Claude77.7%（5H100%/7D77.7%）、Gemini生图55.2%。原始账号字段仍可由/api/quota读取，未混用模型percentage冒充5H/周。80测试、py_compile和页面运行态验证通过。

- 按用户确认清理Antigravity无真实账号绑定：先备份gui_config.json至C:\Users\1\.antigravity_tools\gui_config.json.bak-20261003-034831-before-remove-missing，再移除两条无账号映射（原代理ID对应21022/21012）；保留6条真实邮箱账号绑定。EVA适配层重启后/api/driver-cards与浏览器均实测6卡、6个真实邮箱，80测试通过。未删除账号文件或凭据，仅修改绑定账本。

- EVA自动同步收口：机体卡片与总额度卡均设置15秒刷新；卡片按/api/driver-cards真实绑定数量自动增删，当前6个真实邮箱/6卡；额度按Antigravity quota_groups与模型字段填充。页面运行态实测6卡、6邮箱，Gemini54.9%、Claude77.7%；Python编译与80项测试通过。EVA仍只读同步，不代替Antigravity登录或创建绑定。

- EVA日志显示优化：不改UI布局、不再对用户可见的本地实时日志做无必要脱敏；前端对连续相同消息合并显示并附重复次数（如“已读取真实日志：309条 ×2”），保留真实时间、来源和错误内容，减少重复刷屏。浏览器实测重复维护日志被合并，日志行从重复堆积降为3行可读流。

- 日志筛选反馈修复：ERRORS按钮筛掉正常[MAINT]日志时，原页面为空白且新日志仍不可见；现增加当前筛选状态、实时新日志按筛选条件显示，以及无错误时的明确提示“当前暂无错误日志 · 切换 ALL 查看正常运行日志”。浏览器实测ERRORS下提示出现；ALL仍显示真实滚动日志。

- 日志拓扑盘点与补接：原统一接口只有mihomo bridge、Hermes、Hermes watchdog、AgentProxyHub usage/autonomy五类文本源；发现未接入的Antigravity请求数据库C:\Users\1\.antigravity_tools\proxy_logs.db（request_logs表，约2GB）。新增只读antigravity_requests源，输出时间/方法/模型/HTTP状态/耗时/URL/错误，不读取request_body、token或响应正文；EVA自动日志现在实测包含该源，约510行合并展示。Flow-Tools源码未发现独立正式日志文件，Hermes缓存/数据库未纳入，避免把临时缓存当项目业务日志。

## 回滚点

| 时间 | 仓库 | 提交 |
| --- | --- | --- |
| 2026-09-29 迁移前 | FengWoBridge | `local/custom` `193f000` |
| 2026-09-29 迁移前 | AgentProxyHub | `main` `12b15b8` |
| 2026-09-29 迁移完成 | AgentProxyHub | `main` `de5081e` |

运行数据回滚：`D:\Program Files\FengWoBridge\backups\20260929-134805-pre-agentproxyhub-migration`（迁移前）与 `D:\Program Files\FengWoBridge\backups\20260929-final-pre-retirement`（退役前全量快照）。回滚方式：停掉本项目 mihomo → 恢复蜂窝目录（未动过则直接 `启动桥接.bat`）→ 把自启快捷方式换回 `蜂窝出口桥接.lnk`。
