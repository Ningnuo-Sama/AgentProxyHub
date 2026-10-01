# Hub 候选回归证据

- 命令：`python -m unittest discover -s tests -v`
- 目录：`D:\GitHub\AgentProxyHub\package-candidate`
- 结果：**18/18 通过，0失败**，耗时约10.98秒。
- 覆盖：坏YAML/坏revision拒写、journal中断恢复、provider原子刷新及reload回退、6进程并发绑定/CAS、端口范围、同国策略、拒绝跨国fallback、精确重启计划。
- 本轮未启动 `pool-guard` 的读写模式，未修改正式运行副本，未触碰8045/8001/FengWoBridge。
- `pool-guard` fail-closed执行证据另见 `POOL_GUARD_FAIL_CLOSED_CANDIDATE_20261001.md`。
