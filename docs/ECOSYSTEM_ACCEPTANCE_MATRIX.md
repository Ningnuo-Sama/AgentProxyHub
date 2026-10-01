# 生态统一实施验收矩阵

> 状态：拍版后候选验收基线。未通过的工作包不得切换正式运行；mock通过不等于真实账号、媒体或微信验收通过。

## 0. 共同隔离门禁

| ID | 场景 | 必须证据 | 失败处理 |
|---|---|---|---|
| I-01 | 候选启动 | 脱敏effective config：listen/data/profile/output/policy/production allowlist；所有写路径在候选根；不抢8001/8045/8320/21909 | 停止候选 |
| I-02 | 损坏JSON/写失败 | 生产文件hash/mtime前后零变化 | 修复原子写后重测 |
| I-03 | 候选配置缺失 | 明确拒绝，不fallback到`%LOCALAPPDATA%\FlowTools`或生产Hub | 阻断启动 |
| I-04 | 子进程 | cwd/env/写根同样核验，不只看父进程 | 停止任务 |

## 1. WP-00横切底座

| ID | 场景 | 验收 |
|---|---|---|
| X-01 | 错Key、过期op、重放、未知能力 | 401/拒绝，无业务副作用 |
| X-02 | 非Schema模型输出/GLM失活 | 拒绝危险动作；规则路径继续运行 |
| X-03 | unknown媒体提交 | 持久化`submission_state=unknown`，只查询/人工核对，不重生 |
| X-04 | 预算/取消 | 超预算拒绝；取消只停止等待，不虚报上游取消/退款 |
| X-05 | 账本损坏/CAS冲突 | 不写空账本，保留旧文件并报告 |

## 2. WP-A AgentProxyHub

- **A-01**：同国成功切换；未知国家或跨国拒绝/升级；跨provider仅同国。
- **A-02**：订阅重排、增删节点不改变现役端口语义。
- **A-03**：provider超时、坏YAML、reload失败时单provider隔离并回退；必须真实解析YAML/mihomo结构，备份现役配置并验证reload后再发布；仅出现根键不算通过。
- **A-04**：排空身份租约后切换；当前8045/mihomo控制链不可被维护动作切断。
- **A-05**：MCP与Cloak多进程共写同一生产路径时锁、revision/CAS一致；解析失败禁止以空对象覆盖；数据与revision必须单事务原子提交或有崩溃恢复journal，不能两个文件分步发布；revision损坏拒绝写，不归零。
- **A-06**：禁止宽泛`taskkill /T /F`、直接外写Antigravity私库、无同国时退全局最快节点。

## 3. WP-B Flow令牌与媒体任务

### 凭据

- **B-01**：AT过期自动刷新；仅在字段语义已证实为AT专属expiry时采信服务返回expires_at；否则固定55分钟仅作保守fallback且标记来源，不能把通用session expires当AT寿命。
- **B-02**：ST拒绝→新鲜Profile/Cookies受支持恢复；资料忙等待，不强杀。
- **B-03**：401/403/429/5xx分类；单账号冷却，其他账号继续。
- **B-04**：点数可见、认证健康、业务能力分别状态；点数不得自动解除用户手工排除/security quarantine。
- **B-05**：Profile提取主体与既有account不一致返回409/隔离，不能覆盖email改名串号。
- **B-06**：HTTP refresh与桌面`heal_account`语义一致，不能仅ST换票却宣称完整自愈。

### 未知提交与费用

- **U-01**：供应商已计费后断Socket无task ID→unknown，POST计数仍1。
- **U-02**：POST后落operation_id前崩溃→resume仍不重POST；无法查询则`needs_reconciliation`。
- **U-03**：相同idempotency key并发最多一次；不同prompt同key返回conflict。
- **U-04**：轮询503/超时保持submitted，不回待提交。
- **U-05**：下载/微信失败只重用artifact/Outbox，不重生。
- **U-06**：记录accepted_submit_count、charged_count、artifact_count、outbox_count、sender_attempts。

## 4. WP-C Antigravity

- **C-01**：400输入、地区、401、429、5xx语义分开。
- **C-02**：只解除受影响会话；账号冷却与重试预算；不停止当前8045承载网关。
- **C-03**：真实最小对话记录requested/resolved/upstream模型、endpoint、账号出口和request证据；CLIProxyAPI仅参考，不改无关Owner。

## 5. WP-D Cloak→Flow

- **D-01**：登录/Profile关闭事件或显式同步，Profile锁存在且空闲才导入。
- **D-02**：重复同步幂等；Flow返回409主体不一致；成功不返回Cookie/Token。
- **D-03**：Profile/账号/出口/绑定revision快照一致；Hub当前无revision时只能用脱敏hash核对，不能伪造CAS。
- **D-04**：导入半成功、DPAPI/备份失败不覆盖旧记录；不强杀浏览器。

## 6. WP-E Visual Pro

- **V-01**：图片fixture实际注入Gemini多模态请求，不仅传filename/role/metadata；记录input与payload媒体sha256。
- **V-02**：相同内容改文件名结论一致；同节点版本换内容hash必须cache miss；错图/删图失败或显式缺素材。
- **V-03**：视频抽样覆盖标为`sampled`并列时间点；未看到中尾事件不得声称全片理解。
- **V-04**：audio有真实音频或来源转写；不支持就声明能力缺失。
- **V-05**：requested local alias、resolved route、upstream endpoint/model、request证据分开；models列表不算真实证据。
- **V-06**：LLM离线/超时/经验离线时不影响原节点优化和生成；深度优化默认0媒体提交；不自动外部付费降级。

## 7. WP-F 画布与面板

- **F-01**：原优化按钮和生成路径不变，Visual Pro深度优化并列。
- **F-02**：节点版本变化使旧建议过期，不覆盖新稿；应用/撤销可回退。
- **F-03**：Visual Pro离线时原功能可用；UI键盘/取消/状态明确；宿主实际buildHash核验。
- **F-04**：面板减法不删除创作自由度，运维复杂度进入Agent/高级入口。

## 8. WP-G 微信/手机

- **G-01**：两个明确授权会话交叉测试，绑定recipient/conversation/order/task/artifact。
- **G-02**：同会话有序，跨会话并行；同名联系人/群冲突拒绝。
- **G-03**：无稳定sender/recipient/送达回执不得宣称成功；send失败只Outbox重投原artifact。
- **G-04**：重复webhook/过期事件去重；普通恢复0微信，重要事件和结案各一次；不开放任意shell。

## 9. 执行记录字段（每个Case必须填写）

本矩阵是验收基线，不是通过证明。每个Case执行时必须落一行结构化记录，缺任一字段不得标记通过：

```text
case_id
work_package
status: pending | running | pass | fail | blocked | not_run
command_or_entrypoint
fixture_or_test_account
oracle_expected
actual_result
 evidence_path
rollback_point
cost_limit
message_limit
production_impact
operator_time
```

`mock pass`、`compile pass`、`/health 200`、端口监听和模型列表均只能作为局部证据，不能替代真实业务闭环。真实账号、媒体扣费、微信发送必须分别注明授权、额度、收件对象和结果；未执行写 `not_run`，不要用“预计通过”。

### 当前执行状态（本轮快照）

| 工作包 | 状态 | 已知证据 | 阻断 |
|---|---|---|---|
| WP-00 | blocked | 验收矩阵已创建；P0用例已列 | 横切能力尚未统一实现/验证 |
| A Hub | candidate-pass-partial / independently-reverified | 主会话独立重跑 focused unittest 17/17；journal、损坏revision拒写、真实YAML解析/reload回退、6进程并发/CAS、双国码known策略均有证据 | 尚未整合用户既有 pool-guard.ps1 三处高风险逻辑；正式运行/回退证据未完成，禁止切换 |
| B Flow | blocked / isolated-contract-tested | `cargo check --bins`通过；独立 `rustc --test src\\reliability_contract.rs` 3/3通过；`Account.at_expires_source=session_cap_or_fallback`已补齐；远期session expires仍受55m cap；候选契约覆盖v1状态/时间/operation_id/output_ref恢复、unknown→query、幂等键冲突、显式candidate data_root、account_id+generation lease | reliability_contract.rs尚未注册/接入HTTP、DPAPI任务存储、操作ID轮询或重启执行器；fsync/唯一tmp/跨进程锁/持久化CAS及RefreshLeases跨进程锁未实现；现有refresh_session仍用ST hash互斥；server expires+1h401 mock、冷却契约、cargo test、Release build和真实端到端未完成 |
| C Antigravity | candidate-in-progress | 真实PID43976、8045、/health 200；候选worktree已建 | 真实最小对话和安全恢复未验收；当前网关不可被候选操作 |
| D Cloak | candidate-partial | flow_admission隔离mock/compile通过 | Flow先upsert后主体校验，需Flow修复；无真实事件发布器 |
| E Visual Pro | blocked | 契约草案；服务8320 health 200 | 多模态实现需修正；模型/素材/经验证据未验收 |
| F 画布 | candidate-partial | Seedance typecheck/build、80项首次测试通过 | URI占位sha256、未连真实Visual；Node资源重跑曾因页面文件不足退出 |
| G 微信 | blocked | 只读审计完成 | 无稳定recipient/sender/送达回执；不可真发 |

## 10. 关键补充用例

### Visual多模态事实

- **V-MM-01**：同文件名/尺寸/描述的红圆和蓝方fixture分别识别颜色、形状和位置；oracle独立于被测LLM，仅接受实际媒体payload/可验证URI receipt，不接受metadata/base64存在本身作为理解证明；记录input/payload hash。
- **V-MM-02**：改文件名内容结论一致；**V-MM-03**：同node version换内容hash必须cache miss；**V-MM-04**：视频开/中/尾事件抽样覆盖，未见区域不能声称；**V-MM-05**：音频真实payload或明确unsupported。
- **V-MM-06**：requested alias→resolved route→upstream endpoint/model→request证据分层；模型列表不是证据；**V-MM-07**：服务/LLM/经验离线不影响原节点，深度优化失败不缓存成功。

### Flow未知提交与Token语义

- **B-07**：HTTP 200无AT、soft-error带AT、camel/snake字段、缺失/过去/超长expires、429 Retry-After、网络与地区403分别进入预期状态。
- **B-08**：AT/ST expiry provenance必须记录；`/fx/api/auth/session`通用expires未经AT专属字段证据不得直接作为AT寿命；refresh lock不得以原始ST永久常驻Map key。
- **U-07**：mock计费oracle独立于被测服务；accepted/charged/artifact/outbox/sender计数与预算reserve/consume/refund按idempotency key一次；取消后的late completion归原order。
- **U-09**：任务事实库必须跨进程锁/CAS、唯一临时文件、flush+fsync、目录持久化和启动恢复；完整保存operation_id/output_ref，不得用`persisted`占位；同幂等键必须由持久化唯一约束防双提交。仅进程内BTreeMap或三行旁路文件不得接入生产。当前隔离模块已实现唯一tmp、文件级sync_all、固定任务锁、`claim_prepare_or_get`；主会话已独立验证双进程同key/同revision和revision冲突。目录fsync、完整跨进程RefreshLeases、生产接入与真实上游查询仍未完成。

### Hub账本崩溃与国家策略

- **A-07**：data/revision单事务或journal；写data后写revision前崩溃、revision坏档、锁超时、两个真实消费者进程并写；线程测试不能替代。
- **A-08**：provider真实YAML/mihomo解析、backup/reload失败回退；`dead.country`与`googleCountry`均known且相等才允许候选。

### 微信断线与权限

- **G-05**：手机断线持久化并重启，只补仍有效事件；发送已接受但无ack防重复；错误sender恢复命令检查有效期/重放；无稳定身份不得发送。

## 11. 总切换门禁

1. P0：唯一生产账本、同国策略、Flow主体/健康分层、未知提交不重生、当前网关不自断必须通过。
2. 记录每个候选的源码SHA、exe hash、依赖锁、effective config、PID/路径、数据schema、测试证据。
3. 新→旧→新回退演练，旧版本读取并保留新增binding/order/unknown，不覆盖新增数据。
4. 真实图片/视频/微信均须有明确授权和最小额度/测试对象；无授权标待验。
5. 当前状态分类：设计、代码完成、候选通过、真实验收、正式运行；健康200/构建通过不替代业务证据。
