# Agent 入口

先读 `D:\Agent-JiYi\README.md`、`D:\Agent-JiYi\rules\global-agent-rules.md` 与 `D:\Agent-JiYi\shared\github-local-upstream-workflow.md`，再读本目录 `LOCAL_MAINTENANCE.md`。

本仓库是源码副本，正式运行副本位于 `D:\Program Files\AgentProxyHub`；修改源码不代表已部署。

## 跨项目联动

- `D:\GitHub\FengWoBridge`（前身「蜂窝出口面板」）：本项目由它通用化重构而来。2026-09-29 起正在把它的成熟面板、巡检引擎与运行能力整体迁入本仓库；**迁移完成并验证前，现役出口仍由 `D:\Program Files\FengWoBridge` 提供，不要提前停掉它。**
- `D:\GitHub\CloakMulti`：`cloakmulti/aphub.py` 读本项目 `data/nodes.json`，并与本项目的 MCP 服务端**共写** `data/bindings.json`（环境 → 端口锁定账本）。改动该账本格式必须两边同步。
- MCP 消费方：Claude Desktop / Cursor / DSH 等直接拉起 `mcp/server.py`。工具表由宿主在启动时固化，改完必须重启客户端才生效。

## 硬约束

- 本地出口端口段 `21001-21080`（蜂窝）/ `22001-22045`（星辰）**不得变更**：Antigravity Tools 的 7 个账号粘性绑定直接指向这些端口，改段等于全部失效并触发 IP 漂移风控。
- 严禁把生成配置、订阅凭据、节点数据、日志和二进制提交到 Git（`.gitignore` 已覆盖 `data/`、`bin/`、`release/`）。
