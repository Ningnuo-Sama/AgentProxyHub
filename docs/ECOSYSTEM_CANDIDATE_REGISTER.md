# 生态统一工程候选登记表

> 快照状态：候选冻结审查。登记内容是当前已收到的专项报告，不等于正式运行或上线证明。
> 规则：未记录 base SHA、候选路径、改动归属和测试证据的变更不得集成；生产进程、账号、出口、真实媒体和微信保持不动。

| WP | Owner / 候选 | Base | 当前状态 | 已有证据 | 阻断 |
|---|---|---|---|---|---|
| WP-00 | 主会话文档/验收矩阵 | AgentProxyHub `8a90104` 工作区文档 | implemented_unverified | MASTER、MATRIX已写入并回读；P0/P1用例已补齐 | 横切契约尚未落到统一实现，需逐Case记录command/oracle/evidence/rollback/cost/message；未通过前不得切换 |
| A Hub | `D:\GitHub\AgentProxyHub\package-candidate` | AgentProxyHub `main`，基线报告为 `8a90104` | candidate-pass-partial / independently-reverified / guard-blocked / fail-closed-candidate | 本轮独立重跑 `python -m unittest discover -s tests -v` 18/18；py_compile通过；6进程并发、CAS、journal异常注入恢复、坏账本拒写、坏YAML/空节点拒绝、严格validator/类型检查、reload失败原子回退、双国码策略均有证据；pool-guard静态审计后，候选写入模式已fail-closed、无同国改为升级、宽泛重启改为升级记录，AST parse_ok | 候选尚未接入Hub事务发布器/真实故障注入；生产运行副本未改；不得部署 |
| B Flow | `D:\GitHub\Flow-Tools` 工作区候选 + 已切换运行版 | `local/zcode-dev` `e0e04f3`；运行版 `target\\release` SHA `D7DB864B015D...` | candidate-pass-partial / live-smoke-pass / blocked-for-full | reliability全量5/5、双进程1/1；Rust39通过/0失败/4忽略；OS锁分类Python5/5、Rust1/1；真实`ucesnq`同步HTTP200、hasCookies=true、admissionState=validated、账号池6/6 healthy；启动页令牌持久化修复已部署，PID35648 `/health`、`/v1/models`200；有效持久令牌访问启动页200、无令牌403 | reliability_contract.rs仍未注册HTTP/DPAPI/真实operation查询；RefreshLeases锁/目录fsync/全量恢复未完成；4项完整网络测试仍忽略；旧已打开页面需重开一次获取稳定能力值 |
| C Antigravity | `D:\GitHub\Antigravity-Manager-ecosystem-candidate` | `local/custom` `c4786bd8` | candidate-partial / blocked | recovery standalone3/3、边界probe7/7；修正旧预算断言2/2；工具链Rust1.98.1与libcore完整；此前lib test target `--no-run` exit0；本轮重新定位cargo test阻断为缺失候选`../dist` frontendDist配置 | recovery仍未接handler；当前cargo test在Tauri宏阶段因`frontendDist ../dist`不存在阻断；未运行npm build、未真实模型/多模态验收；live PID19868未动 |
| D Cloak | `D:\GitHub\CloakMulti` 工作区候选 `flow_admission.py` + `webui.py` + `launcher.py` | `main` `7dc4fa5` 工作区 | candidate-pass-partial / blocked | `compileall`；准入测试9/9；现役7800已加载；launcher自动idle；已登记账号无login事件可reconcile；flow-03 stale runtime已修复，新PID62764/CDP8277；关闭资料后真实Flow同步HTTP200、hasCookies=true、admissionState=validated，账号池6/6 healthy | binding revision/CAS生产证据和重复同步实跑未完成；未签字为全量active，仍保留候选阻断 |
| E Visual Pro | `D:\GitHub\ariadne\tools\ariadne-visual-pro` | `ariadne` `619b836` 工作区 | candidate-pass-partial / blocked | 主会话独立全量193/193、deep-optimize原10/10；本轮deep-optimize专项12/12，实际文件SHA-256校验、bytes/hash证据、错哈希进入unavailable且不进入Gemini payload；`git diff --check`通过 | `scene_service.py`混有用户改动和候选路由，尚未Owner审阅/接入；未真实Gemini/8320、未生成媒体或付费请求；Canvas宿主契约仍未验收 |
| F Canvas | `D:\GitHub\daedalus-canvas-plugins\ariadne\seedance-2.5` | `main` 插件基线 | candidate-pass-partial / blocked | 本轮 `npm test -- --runInBand` **84/84通过**；typecheck通过；build通过，产物同步至宿主public插件目录；深度优化包含真实素材哈希/版本保护测试 | 真实Visual后端与宿主运行时未连；未真实画布验收；候选产物未启用生产路由；React测试有既有warning但无失败 |
| G Phone | `D:\GitHub\手机分身` | `local/custom` `035b45d` | blocked | 只读审计 | 无稳定recipient/sender/delivery ack；专项失败/未形成安全候选；禁止真发 |

## 当前运行快照（只读证据）

- mihomo：PID 32272，`D:\Program Files\AgentProxyHub\bin\mihomo.exe`。
- Flow：PID 59188，源码运行构建 `D:\GitHub\Flow-Tools\src-tauri\target\release\flow-tools.exe`，监听8001；维护文档中的merged-candidate记录已过时。
- Antigravity：PID 43976，`D:\Program Files\Antigravity Tools\antigravity-tools.exe`，监听8045，曾核验 `/health` 200/version 4.8.2-beta.0。
- Visual Pro：8320 `/health` 曾返回200；这只证明素材服务健康，不证明Gemini深度优化或任务恢复。
- Cloak：7800运行者与外层壳PID需区分，不能仅按壳进程判断。

## 集成顺序

1. WP-00统一任务/能力/事件/预算/取消/审计契约，建立每Case执行记录。
2. A Hub候选修复与真实隔离故障注入；不直接改写用户的`pool-guard.ps1`，先认领后最小修改。
3. B Flow完成凭据语义与未知提交幂等；其后D Cloak才可进入生产激活。
4. C Antigravity只在候选handler接入、工具链恢复后复核；当前8045不能被候选控制。
5. E Visual Pro真实素材安全输入后，F Canvas才可接入并做真实宿主验收。
6. G Phone最后，除非出现明确授权测试对象和稳定送达回执。

## 发布门禁

- 任一P0/P1阻断未关闭：只允许候选，不集成、不部署。
- 代码通过、健康200、端口监听、mock通过均不等于真实验收。
- 所有正式切换必须记录候选SHA、产物hash、effective config、PID/路径、数据备份、回退点和证据路径。
- 禁止外部付费媒体/LLM自动降级；禁止随机微信联系人；禁止删除或覆盖现有用户脏工作。
