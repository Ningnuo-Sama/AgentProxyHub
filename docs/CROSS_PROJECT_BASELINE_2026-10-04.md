# Flow-Tools × AgentProxyHub 跨项目冻结与下一版索引

## 冻结版本

| 项目 | 源码基线 | 分支 | 正式运行状态 |
|---|---|---|---|
| Flow-Tools | `ff60b16931992ef0f83ae3a099a3dce14ed371d3` | `local/zcode-dev` | dirty runtime，未证明对应 |
| AgentProxyHub | `696c399784c7ef564307cb1b112c384762d273d4` | `main` | runtime drift，未同步 |

冻结标签只代表各自源码提交，不代表生产切换或真实媒体功能通过。

## 职责契约

- AgentProxyHub：代理、地区约束、节点健康、候选发现、预算策略和通知；不直接创建验证码任务。
- Flow-Tools：媒体协议、账号调度和实际验证码执行；接受 AgentProxyHub 的策略结果。
- Hermes：微信通知出站；必须验证 gateway 状态与 `success=true`。

## 下一版共同门禁

静态检查、测试、隔离运行、接口契约和脱敏审计全部通过后，才允许候选发布。真实验证码、媒体生成、充值、正式换绑和运行版本切换均需单独授权。失败或环境不明立即熔断，保留脱敏证据。

## 当前阻断项

- 两仓库均存在未提交改动。
- Flow-Tools 运行 debug 二进制无法证明对应冻结提交。
- AgentProxyHub 源码与正式运行副本不一致。
- 版本号、构建物和运行记录尚未统一。
- 尚未完成跨项目验证码策略接口实现和端到端契约测试。
