# AgentProxyHub 两提案极速落地任务书（纠偏版）

> 依据：`ARCHITECTURE_DIRECTIVE_FOR_GPT_20261001.md`、`UNIFIED_ARCHITECTURE_AND_FEATURE_PROPOSAL_20261001.md`
> 目标：先打通可回退的最小闭环，再补体验与跨仓库联动；不等待“大而全”设计。

## 0. 先锁死的纠偏结论

1. **不执行 21101-21106 迁移。** 项目硬约束明确禁止改变 `21001-21080` / `22001-22045`；账号前台保持现有 7 个粘性绑定。后端只能在同国家/同大区候选节点中切换底层出口，不能改变前台端口。
2. **不按总纲中的 6 账号清洗 `gui_config.json`。** 现场维护记录和历史事实是 7 个账号；在读取实际配置并逐账号验证前，禁止删改账号。
3. **`vault.enc` 不写源码仓库 `data/`。** 源码只提供模块；密文放正式运行数据目录（默认 `D:\ProgramData\AgentProxyHub\data\vault.enc`，可由环境变量覆盖），绝不入 Git。
4. **FengWo 不直接退役。** AgentProxyHub 当前仍可能依赖其上游出口；只有新中枢完整接管、实测通过、具备回滚点后，才允许切换。
5. **先做 AgentProxyHub 单仓 MVP。** Flow-Tools、CloakMulti、鲸管家、手机分身的联动先以契约和适配器接口冻结，不在本轮跨仓库大改。

## 1. 交付范围（极速版）

### P0：今天完成，必须可运行

- 上游源统一账本：读取 `data/upstreams.json`，支持 `api_token`、`subscription_url`、`profile_path`。
- `core/upstream_fetcher.py`：按源拉取节点，规范化为 `{name, server, port, type, country, provider_id}`，去重并输出候选快照；网络失败不覆盖上一份有效快照。
- MCP 新增 `refresh_upstream_nodes`：默认只读/安全刷新，返回新增、保留、失败源，不回显 Token。
- 路由选择坚持现有物理端口：新增逻辑策略函数按国家/健康等级选候选，不创建 211xx 监听。
- 快速回归：`python -m py_compile`、`python mcp/test_mcp.py`、离线上游解析测试。

### P1：下一批

- `core/vault_manager.py`：Windows DPAPI 加密模型与原子读写；旧版明文只允许一次性迁移，迁移后不再读取明文 Token。
- MCP 凭据工具改为只读脱敏；高危 AK/SK 只进入存储签名沙盒，不提供通用转发。
- `pool-guard.ps1` 接入逻辑策略选择：绑定账号端口不变，仅替换该端口背后的节点配置；连续失败、防抖、同区优先。

### P2：联动上线

- Flow-Tools：消费 `get_route_target`/本地 HTTP 代理契约，先读后切；保留 210xx 端口。
- CloakMulti：只调用现有 MCP/本地适配器，不直接改 `bindings.json` 结构。
- 告警适配器：鲸管家 `127.0.0.1:8766/notify`、手机分身 `127.0.0.1:48921` 均采用可选 webhook；失败只记日志，不阻塞自愈。
- Gemini/GLM 决策器只接收结构化健康快照，输出严格 `HEALTHY|REBIND|QUARANTINE`；模型不可直接写配置。

## 2. 最小接口契约

### `refresh_upstream_nodes`

输入：

```json
{"provider_ids": ["provider_a"], "dry_run": false}
```

输出：

```json
{
  "ok": true,
  "snapshot_path": "...运行数据路径...",
  "sources": [{"provider_id":"provider_a","status":"ok","fetched":80,"accepted":78}],
  "total_nodes": 78,
  "warnings": []
}
```

失败原则：单源失败不清空旧节点；全部失败返回 `ok:false`，保留旧快照。

### 逻辑路由

输入：`country`、`min_rating`、`exclude_ports`。
输出：候选物理端口及原因。任何自动换线只能改变该端口的后端节点，不改变账号绑定端口。

## 3. 分阶段执行与验收

### Phase 1：中枢内闭环

- [x] 新增上游抓取模块与离线解析测试。
- [x] MCP 刷新工具可列举、可调用、Token 不回显。
- [x] 现有端口范围继续沿用（未创建 211xx 监听；完整实机端口对账待候选运行验证）。
- [x] 节点快照原子写入，失败回退旧快照。

命令：

```powershell
python -m py_compile core/upstream_fetcher.py mcp/server.py mcp/test_mcp.py
python mcp/test_mcp.py
python -m unittest discover -s test -p "test_*.py"
```

### Phase 2：凭据与守护

- [ ] DPAPI 密文写入运行数据目录。
- [ ] `pool-guard.ps1 -Mode Inspect` 实测通过。
- [ ] `AutoGuard` 仅做同区后端切换，账号端口不变。
- [ ] 记录回退点，正式副本切换前不停止现役 FengWo 上游。

### Phase 3：跨仓适配

- [ ] Flow-Tools/CloakMulti 先读契约再接入。
- [ ] 双信使均不可用时不影响主链路。
- [ ] 端口、账号数量、绑定关系、节点数据逐项对账。

### Phase 4：上线

- [ ] 源码测试通过。
- [ ] 候选运行副本启动并通过真实 curl/MCP/UI 验收。
- [ ] 保存当前/上一可运行版本与运行数据备份。
- [ ] 先本地提交，再按用户授权推送；不强推、不覆盖他人提交。

## 4. 明确不做

- 不创建 21101-21106 新端口。
- 不清空或重写 Antigravity 账号池。
- 不把订阅 Token、节点快照、日志、密文提交 Git。
- 不在未验证的情况下停止 FengWo、切换正式运行副本或联动其他仓库。
