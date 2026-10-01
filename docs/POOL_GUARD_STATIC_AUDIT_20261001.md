# pool-guard.ps1 只读静态审计

审计对象：`package-candidate/scripts/pool-guard.ps1`。本轮未执行脚本、未修改生产配置、未重启任何服务。

## 结论

该脚本当前只能作为候选审计材料，不能进入正式 AutoGuard。发现三处 P0 风险：

1. **无同国节点时跨国回退**：AutoGuard 在第 240–251 行进入全局 `$sortedCandidates`，只排除 China/Hong Kong/Macao，不再要求目标国家相同。违反严格同国路由。
2. **直接写 Antigravity 私库**：第 26、50–52、316–337 行直接读取并覆盖 `C:\Users\1\.antigravity_tools\gui_config.json`，并更新 `反重力-Gemini可用-socks5.txt`。这绕过 AgentProxyHub 的正式账本/CAS/租约与备份发布流程。
3. **宽泛强杀进程树**：第 346–355 行在 `-RestartGatewayIfChanged` 下枚举 `antigravity-tools`，对每个进程执行 `taskkill /PID ... /T /F`。这可能切断现役 8045 及其子进程，不符合“排空租约后切换”和禁止宽泛 taskkill 的门禁。

## 其他观察

- 第 81–129 行对已绑定账号做探测，`AutoGuard` 可据此触发换绑；但没有与共享 bindings revision/CAS 做原子事务核对。
- 第 316–329 行直接覆盖配置，虽有 `.bak` 和回读校验，但不是临时文件+原子替换，也没有目录 fsync / journal / 多进程锁。
- 第 140–179 行并发扫描固定端口段；端口范围仍是 21001–21080 与 22001–22045，未发现改段证据。
- 第 224–237 行同国候选匹配是正确方向，但第 240 行后的 fallback 破坏了该约束。
- 第 351 行实际命令目标是所有名称匹配的 `antigravity-tools` 进程，目标路径随后固定启动 `D:\Program Files\Antigravity Tools\antigravity-tools.exe`，未核验现役租约/版本/回退哈希。

## 验收状态

- 命令：只读 `read` 审计源码；未启动脚本。
- 证据：精确源码行号见上；未将静态审计冒充故障注入或部署验收。
- 回退：本轮没有产生生产改动，因此无回退动作。
- 下一安全动作：在隔离候选中移除跨国 fallback，改为 `escalate/no substitute`；把写入改成 Hub 自有事务和 revision/CAS；把重启改为租约排空+单实例有界控制，之后再做故障注入与回退演练。
