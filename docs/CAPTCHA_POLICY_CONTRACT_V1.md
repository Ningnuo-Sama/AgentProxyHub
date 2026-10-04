# 验证码策略契约 v1（dry-run）

## 职责

AgentProxyHub 只负责验证码策略、预算判定和审计决策；Flow-Tools 负责实际验证码供应商调用。v1 永远不创建 YesCaptcha 任务、不返回 Key、token、Cookie 或签名 URL。

## 请求

本机调用方提交 `contract_version=1`、`mode=dry_run`、稳定脱敏的 `request_id`、`operation`、`stage`、`route`、上游状态/错误分类和单请求 `budget`。不得提交完整提示词、账号凭据、Cookie、session/access token 或验证码 token。

## 决策

v1 只返回 `deny`、`allow_local` 或 `defer`：

- 未明确出现验证码错误：`captcha_not_indicated`
- 401、无效会话或无效 Cookie：`auth_failure_circuit_open`
- 已提交/已有任务：`already_submitted`
- 预算耗尽：`budget_exhausted`
- 路由未知：`route_unknown`
- 明确验证码错误且允许本地路径：`allow_local`
- 需要付费供应商：`paid_authorization_required`，当前仍为 `defer`

AgentProxyHub 不因服务不可达、版本不兼容或未知字段而放行付费任务；调用方必须 fail-closed。

## 验收

使用本地替身测试无验证码、401、明确验证码、本地路由、预算耗尽和非 dry-run。验收必须证明 `would_create_task=false`、`max_new_tasks=0`，并扫描日志无 key/token/cookie/prompt/签名 URL。真实 YesCaptcha、媒体生成、充值和正式部署不属于 v1 零付费验收范围。
