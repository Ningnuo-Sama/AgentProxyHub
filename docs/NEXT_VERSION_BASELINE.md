# AgentProxyHub 下一版本开发与自主验收基线

## 目标

让低成本模型可以在白名单范围内自主执行只读审计、静态检查和隔离候选验收；确定性工具负责测试结果，模型不得把推断当事实。

## 版本入口

- 上一冻结源码：`696c399784c7ef564307cb1b112c384762d273d4`
- 分支：`main`
- 正式副本：`D:\Program Files\AgentProxyHub`，未同步即标记 `runtime_sync=blocked`。
- 每次变更记录源码 SHA、运行副本 SHA、数据快照位置和回退点。

## 门禁

1. `git status --short --branch` 和 `git diff --check`。
2. Python AST/`py_compile`，PowerShell Parser，单元测试和 MCP 契约测试。
3. 检查端口段未变、`bindings.json` 语义未变、敏感目录未入 Git。
4. 隔离候选运行后核对 `/health`、进程路径、关键端口和控制器认证错误处理。
5. 代理真实出口测试须记录国家、时间和证据新鲜度；不以旧 `nodes.json` 评级替代实测。
6. 跨项目验证码策略仅测试 dry-run/替身；禁止无授权创建 YesCaptcha、媒体生成、充值或正式换绑。
7. Hermes 告警必须同时满足 gateway `running/connected` 和发送结果 `success=true`。

## 失败熔断

认证、权限、凭据泄露、跨大区候选、控制器异常和付费边界不明时立即停止。无副作用检查最多重试一次；禁止自动改生产绑定、自动充值、自动发布或绕过安全门禁。

## 自主验收命令

```powershell
git status --short --branch
git diff --check
python -m py_compile core\*.py mcp\*.py tools\*.py
python -m unittest discover -s test -p "test_*.py"
python mcp\test_mcp.py
Get-FileHash mcp\server.py
Get-FileHash "D:\Program Files\AgentProxyHub\mcp\server.py"
```

`mcp/test_mcp.py` 和网络/端口测试执行前须确认副作用；无法确认则只做静态测试并标记未执行。

## 报告模板

```text
项目/版本：
源码提交与运行副本 SHA：
端口/绑定契约：
执行门禁与命令：
结果：通过 / 失败 / 未执行
运行副本同步：通过 / 阻断
代理实测与地区证据：
通知链路：gateway 状态 / send JSON success
付费调用：未执行或已授权
未验证项、熔断和回退点：
结论：通过 / 阻断 / 有条件通过
```
