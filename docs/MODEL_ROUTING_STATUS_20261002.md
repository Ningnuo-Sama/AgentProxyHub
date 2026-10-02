# 三模型驻场工程师路由状态

## 当前策略

- 日常主战：Gemini 3.8 Flash Tiered（Antigravity 本地网关）
- 低成本兜底：GLM-5.3-Flash（智谱）
- 最高事态：GPT-6.1-SOL（AICost）
- 图片、视频、音频：不由文本模型直接提交，统一交给 Flow-Tools

## 已实现

- `core/model_router.py`：统一文本完成接口和三模型凭据解析。
- Gemini 失败时自动尝试 GLM。
- critical 任务走 GPT-6.1-SOL。
- DPAPI 金库只在调用时解密，凭据不返回、不写日志。
- 调用 usage 写入脱敏账本。
- 驻场工程师增加 `model_status`、`model_complete` 白名单动作。
- EVA H5 适配层增加 `/api/models`、`/api/complete`。
- 媒体请求返回 Flow-Tools handoff，不在这里提交生成。

## 现场验证

- 三个模型凭据配置状态：均为 configured=true。
- Gemini 日常真实调用：成功，返回 `gemini-3.8-flash-tiered`。
- GPT 最高事态真实调用：成功，返回 `gpt-6.1-sol`。
- Gemini 故障模拟：确实进入 GLM 兜底分支。
- GLM 重新核验：发现两条 DPAPI 金库条目（`zhipu.txt`、`智谱决策专用.txt`），分别单独使用目标模型 `glm-5.3-flash` 探测；两条均能成功访问 `/models` 且模型目录包含目标模型，但 `/chat/completions` 均返回 HTTP 429，错误码 1113：余额不足或无可用资源包。路由已固定优先使用 `智谱决策专用.txt`，不再误选普通条目；当前阻塞是智谱上游资源响应，不是模型 ID 或代码端点错误。
- Flow-Tools 健康检查：HTTP 200；尚未提交媒体生成任务。
- Python 编译：通过。
- 全部现有 unittest：27/27 通过。

## 运行边界

本次未提交图片、视频或音频生成；未将模型密钥写入源码、日志或 Git。源码修改尚未复制到 `D:\Program Files\AgentProxyHub` 正式运行副本；MCP 客户端如要加载新增工具动作，需重启后重新拉起 `mcp/server.py`。
