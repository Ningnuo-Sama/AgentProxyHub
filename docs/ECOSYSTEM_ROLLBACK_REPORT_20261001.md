# 生态回退报告（脱敏）

## 范围与原则

本报告只覆盖本实施会话实际发生的变更。回退动作必须先确认端口、PID、路径和文件哈希；不得宽泛 `taskkill /T /F`，不得删除浏览器资料或锁文件，不得跨国重绑代理。

## 已上线变更与回退点

### Flow-Tools 网关

- 当前路径：`D:\GitHub\Flow-Tools\src-tauri\target\release\flow-tools.exe`
- 当前运行 PID：`35648`
- 当前 SHA256：`D7DB864B015D0E530A53F8710832CB3A0A833316C26092B6B32ACD1F91F4643A`
- 已上线内容：Profile OS 锁精确分类、主体邮箱先校验后 upsert、`profile_busy`→409、启动页本机能力值持久化。
- 回退点：切换前旧稳定二进制复制到临时目录 `flow-launcher-rollback-*`；另有独立 `target\ecosystem-release` 产物作为回退/对照。
- 回退步骤：确认8001租约/调用停止→记录旧PID与哈希→有界等待进程退出→恢复已核验旧 exe→启动→验证 `/health` 与 `/v1/models`；失败则停止新进程并恢复旧副本。
- 数据注意：不回滚 `%LOCALAPPDATA%\FlowTools` 账号数据；`launcher-token` 是本机随机能力值，不是凭据，旧二进制若与其不兼容只需重开启动页，不删除账号资料。

### CloakMulti

- 当前监听：`127.0.0.1:7800`，项目 venv 启动。
- 已上线/加载：安全准入路由、固定跨进程准入锁、launcher 退出时无凭据 idle 事件、已登记账号 idle reconcile 候选逻辑。
- 回退步骤：仅停止并重启 GUI 监听进程；不停止其他浏览器、不删除 `profiles`、不删除 `instance.lock`；恢复上一个源码/进程入口后验证 `/api/state`。
- 账号数据：真实 `ucesnq` sync-profile 已成功，回退 Cloak 源码不得回写/清除 Flow 账号行；如需业务回退，仅由 Flow 账号备份/事务工具处理。

### AgentProxyHub

- 正式运行副本未切换，FengWoBridge 仍为现役出口运行源。
- `pool-guard.ps1` 只在 `package-candidate` 修改并 fail-closed；没有生产回退动作。
- 回退方式：删除/弃用候选入口，不接入正式计划任务；生产 `D:\Program Files\AgentProxyHub`、FengWoBridge 和 `data/bindings.json` 未由本轮改写。

## 未部署候选（无需生产回退）

- Flow reliability_contract：未接 HTTP/DPAPI/任务库/真实 operation 查询。
- Antigravity recovery：未接 handler；候选完整测试受缺失 `../dist` 阻断；live PID19868未动。
- Visual Pro `scene_service.py`/8320：未接生产、未调用 Gemini、未付费。
- Seedance/Canvas：候选插件未启用，未改变宿主。
- 手机/微信：未发送消息、未改 Outbox、无真实 delivery ACK。

## 现役安全检查

- Flow `/health`：200，PID35648。
- Antigravity `/health`：200，现役PID未动。
- Cloak `/api/state`：200。
- 无跨国代理重绑证据；未执行宽泛进程树强杀。

## 结论

本轮没有全量生态切换，因此不存在“全量版本一键回退”这一事实。已上线组件均有局部回退路径；未部署候选不需要生产回退。总切换门禁保持关闭，直至 WP-00、Flow未知提交/任务恢复、Hub事务发布、Antigravity真实对话、Visual/Canvas真实后端和微信送达ACK全部完成。
