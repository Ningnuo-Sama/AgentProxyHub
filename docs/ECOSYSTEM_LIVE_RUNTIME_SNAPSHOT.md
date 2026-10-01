# 生态当前运行快照

采集时间：Round 35 主会话实时检查（2026-10-01）

## 最新网关状态（含主体校验防护）

- **第三次切换完成**：重建 Release 并确认新二进制包含「资料主体不一致」fail-closed 防护（二进制内已检索到该字符串）。
- 当前 PID `35648`；`/health` 200，`/v1/models` 200。
- 最新运行版 SHA256：`D7DB864B015D0E530A53F8710832CB3A0A833316C26092B6B32ACD1F91F4643A`。
- 已部署启动页令牌持久化修复：随机能力值保存于 `%LOCALAPPDATA%\FlowTools\launcher-token`（仅本机能力值，不含账号凭据），本次重启后文件存在且长度35；旧版回退副本位于临时回退目录。
- 本次构建将 sync-profile 的目标账号邮箱约束前置到任何 upsert 之前，并返回 `admissionState=validated`；桌面导入仍使用无目标约束模式。
- 真实 sync-profile 已取得：ucesnq 资料释放后 HTTP200，`hasCookies=true`、`admissionState=validated`、credits=1050；账号池复查6/6 healthy。
- 此前运行的 `C43C70C0...` 版本**不含**该防护（14:59 构建早于工作区修复），已替换。
- Cloak→Flow 纳管的运行时前置阻断（先upsert后校验）已在运行版移除；launcher退出时自动发送无凭据idle，登记账号可触发目标邮箱reconcile；真实 ucesnq 同步已完成，但binding revision/CAS与重复同步仍未完成。

## 号池当前状态

- 6 个账号：最近一次真实复查为 **6 个 `healthy`**（包含 ucesnq，profile 84a1f699 / 端口 22002）；本轮未重新读取账号明细，不将服务健康冒充账号复查。
- 已实测 22002 出口可打通 `labs.google:443`（alive）。
- `flow-03-Google-Flow` 启动异常已定位并修复：旧 `running/flow-03.json` 指向不可连接CDP且日志有重复启动记录，属于 stale runtime record，不是凭据有效性证据。
- 已仅关闭并重启 `flow-03`：新 PID `62764`，新 CDP `8277`，`/json/version` 返回 Chrome/146.0.7680.177；22002绑定未变。
- 资料已受控关闭并释放浏览器主进程；`sync-profile` 随后真实返回 HTTP200：目标邮箱 `ucesnq@gmail.com`、`hasCookies=true`、`admissionState=validated`、credits=1050、绑定出口 `161.153.127.239`。
- Flow 账号池随后查询为 **6/6 healthy**；未打印或持久化 Cookie/Token。
- 生图冒烟产物：`D:\AI Flowtools\download\images\ecosystem-live-smoke-20260930.png`（已视觉核验）。

## 现役服务实时状态

| 服务 | 事实 | 证据 |
|---|---|---|
| Flow 网关 | 127.0.0.1:8001，HTTP `/health` 200（PID35648）；上一轮 `/v1/models` 200 | PID 35648，稳定路径 `target/release`，SHA `D7DB864B015D0E530A53F8710832CB3A0A833316C26092B6B32ACD1F91F4643A`；启动页能力值已持久化 |
| CloakMulti | 127.0.0.1:7800 `/api/state` 200；准入模块和launcher空闲通知已加载 | Round35实时检查200；flow-03已关闭并完成真实同步，当前未占用资料 |
| Antigravity | 127.0.0.1:8045 `/health` 200 | PID 19868，4.8.2-beta.0；本轮未重启 |
| mihomo | 进程存在 | PID 48544，FengWoBridge运行副本 |
| Visual/素材服务 | 127.0.0.1:8320 `/health` 200 | 仅证明素材服务，不证明Gemini能力 |

## 本轮候选验证

- Hub：主会话独立重跑 **18/18** 通过；pool-guard隔离候选已对RefreshStandby/AutoGuard fail-closed，未整合生产运行副本、未正式部署。
- Flow：锁分类Python **5/5**、Rust分类 **1/1**；完整Rust **39通过/0失败/4忽略**；真实 `ucesnq` sync-profile HTTP200，目标邮箱/hasCookies/admissionState 均验收，复查账号池 **6/6 healthy**；reliability_contract仍未接生产任务库/真实operation查询。
- Visual Pro：主会话独立全量 **193/193** 通过；deep-optimize **10/10**；未接 `scene_service.py`。
- Cloak：主会话使用项目venv独立运行stdlib unittest **2/2通过**；真实7800事件路由拒绝不存在环境（400）及token字段（400），已读取JSON验证ok=false。只完成事件接收接口上线，浏览器自动事件发送、真实凭据同步和active/CAS尚未验收。
- Cloak GUI恢复过程中，直接调用uv基座Python因缺psutil失败；已用项目venv恢复，不安装全局依赖。
- Antigravity：8045健康，但候选仍未接handler，保持blocked。

## 关键限制

- 网关在线不等于所有账号业务可用；最近日志仍有代理漂移、出口失败、Cookie/401、验证码网络失败。
- 没有跨国重锁、清除冷却、绕过主体校验或发送微信。
- Canvas真实素材本机路径+64位SHA、Visual Pro真实Gemini、Cloak生产事件源、Antigravity handler、微信稳定身份/送达ACK仍未完成。
