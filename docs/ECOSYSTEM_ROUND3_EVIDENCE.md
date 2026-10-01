# 第3轮执行证据与范围

## 实际命令

- 在 `D:\GitHub\AgentProxyHub\package-candidate` 执行 `python -m unittest discover -s tests -v`：17项通过，耗时10.089秒。
- 在 `D:\GitHub\Flow-Tools\src-tauri` 执行 `rustc src\\native_lock_probe.rs -o target\\native-lock-probe.exe; & target\\native-lock-probe.exe`：PASS，验证独立进程竞争、父句柄释放、子进程`process::exit`释放锁。
- 在 `D:\GitHub\Flow-Tools\src-tauri` 执行 `rustc --test src\\reliability_contract.rs -o target\\reliability-contract-tests.exe; & target\\reliability-contract-tests.exe`：5项通过。
- 同一测试进程执行 `... --exact tests::two_processes_claim_once_and_revision_conflicts --nocapture`：1项通过。
- 在 `D:\GitHub\ariadne\tools\ariadne-visual-pro` 执行 `python -m unittest discover -s tests -v`：191项通过，其中包含8项deep_optimize候选测试。

## 证据解释

Hub测试覆盖隔离模块和模拟故障，不是生产切换；异常注入不是真实进程kill。Provider候选仍须审查跨进程刷新、生产mihomo语义和pool-guard整合边界。

Flow候选已证明本机OS文件锁基础语义，以及任务锁下双进程同key claim/revision冲突；仍未证明目录持久化、生产RefreshLeases、真实上游operation_id查询，未接入网关/HTTP/生产任务库。

Visual Pro模块测试通过不等于scene_service.py路由已安全接入，当前工作树混有用户改动；未启动8320、未调用Gemini、未生成媒体。

## 保持不变

不接入真实网关，不修改真实账号，不切换生产，不生成媒体，不发送微信。整体目标尚未完成，继续候选实现和验证。
