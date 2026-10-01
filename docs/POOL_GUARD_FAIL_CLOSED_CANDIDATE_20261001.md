# pool-guard fail-closed 候选

对象：`package-candidate/scripts/pool-guard.ps1`。

## 改动

- `RefreshStandby` / `AutoGuard` 在候选中立即拒绝，避免继续直写 `C:\Users\1\.antigravity_tools\gui_config.json` 或导出清单。
- 原无同国候选时的全局最快节点 fallback 已改为 `ESCALATE_NO_SAME_COUNTRY`，不跨国换绑。
- `-RestartGatewayIfChanged` 不再执行 `taskkill /T /F` 或直接启动 Antigravity；只记录 `ESCALATE_GATEWAY_RESTART`，交由受控发布器处理。

## 验证

- 先前通过 PowerShell AST 字符串解析：`parse_ok`。
- 实际尝试 `-Mode AutoGuard` 时，当前 Windows PowerShell 对无 BOM UTF-8 中文源码按本地代码页解码，出现解析错误；脚本未进入业务逻辑，也未读写生产配置。
- 已将候选脚本固定为 UTF-8 BOM；重新执行 `-Mode AutoGuard` 后在第42行明确抛出“RefreshStandby/AutoGuard 已禁用”，证明 fail-closed 分支生效。
- `RefreshStandby` 与 `AutoGuard` 两种写入模式均重复验证为第42行拒绝；随后实测现役 Antigravity `/health` 仍为ok、Flow `/health`仍为ok(PID35648)。
- 本轮仍未触碰 8045、FengWoBridge 或端口绑定；不能把该拒绝验收冒充正式故障注入或部署验收。

## 后续

需在 Hub 事务发布器中实现：同国候选、bindings revision/CAS、原子配置/journal、租约排空、回退哈希和真实故障注入，然后才能恢复任何写入模式。
