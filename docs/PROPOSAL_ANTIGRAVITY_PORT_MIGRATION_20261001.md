# 提案：Antigravity Tools 代理池迁移与 AgentProxyHub 虚拟端口路由联动规范

> **文档代号**: PROPOSAL-AG-APHUB-ROUTING-20261001  
> **状态**: 提案编制完成 / 待 GPT 细化设计落地 / 待最终拍板实施  
> **联动标的**: `C:\Users\1\.antigravity_tools\gui_config.json` 与 `D:\GitHub\AgentProxyHub`

---

## 一、 核心痛点与原则对齐

1. **痛点**：
   * 原 `gui_config.json` 中堆叠了 26 个历史遗留的碎片代理配置，端口分散（21034、22021、22024、22010、22038、22002 等），维护繁琐且极度臃肿；
   * Antigravity Tools 原作者自带的公共代理池调度（RoundRobin/Random）算法过于简陋，缺乏时序置信度、缺少防漂移一票否决机制，如果放开随机轮询必然触发 Google 跨国风控封号。
2. **原则契约（前稳后活）**：
   * **前端账号死锁（Strict Account-Port Pinning）**：每个 Google 账号依然严格实行“一号一固定端口”，杜绝不同账号会话交叉污染；
   * **后端虚拟端口路由（Virtual Port Routing）**：Antigravity 看到的固定端口，其底层实际出口由 AgentProxyHub 在同大区（Same Region）内根据置信度评分自动轮换与自愈，Downstream 零感知。

---

## 二、 现状对账：6 个活跃 Google 账号与目标通道

| 账号标识 | 用户名 / 角色 | 现役端口 | 现役国家/属地 | 目标标准化通道 (新端口设计) | 后端挂载策略组 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `korinenox00@gmail.com` | Rag | `22021` | 加拿大 (CA) | `127.0.0.1:21101` (通道 CA) | AgentProxyHub 加拿大专线策略组 |
| `serendipity4518@gmail.com` | no no | `22024` | 英国 (UK) | `127.0.0.1:21102` (通道 UK) | AgentProxyHub 英国专线策略组 |
| `hamisujko14@gmail.com` | 01 BOT | `22023` | 法国 (FR) | `127.0.0.1:21103` (通道 FR) | AgentProxyHub 法国专线策略组 |
| `vxjsjxyxsnvxuxnz75@gmail.com` | 02 BOT | `22010` | 台湾 (TW) | `127.0.0.1:21104` (通道 TW) | AgentProxyHub 台湾家宽策略组 |
| `393usdb@gmail.com` | Michelle Roberts | `22038` | 墨西哥 (MX) | `127.0.0.1:21105` (通道 MX) | AgentProxyHub 墨西哥专线策略组 |
| `ucesnq@gmail.com` | William Lewis | `22002` | 美国 (US) | `127.0.0.1:21106` (通道 US) | AgentProxyHub 美区纯净策略组 |

---

## 三、 迁移与收口实施步骤（待交付 GPT 细化）

1. **安全快照**：
   * 执行前自动归档 `C:\Users\1\.antigravity_tools\gui_config.json.bak-pre-standardize-20261001`；
2. **清理冗余配置**：
   * 彻底剔除 26 个杂乱代理中未绑定的历史废弃条目，仅收口保留 6 个标准化通道；
3. **重写 `account_bindings` 账本**：
   * 将 6 个账号的标准 UUID 重新绑定至新规范的专属通道 ID，确保配置轻量、语义清晰；
4. **AgentProxyHub 后端生成对应策略组**：
   * 生成脚本（`gen-config.ps1`）为 `21101-21106` 暴露同区策略组（`select` 或 `url-test`），由置信度引擎执行后台同区自愈。

---

## 四、 成果预期

* **体积暴降**：配置文件由 40KB 大幅精简至清晰可读；
* **维护极简**：每个号走哪个通道固定不变，排障一目了然；
* **零封号风险**：账号前台死锁不动，后台同区自愈，兼顾纯粹稳定性与无感自愈力。
