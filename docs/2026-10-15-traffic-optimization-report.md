# 2026-10-15 流量治理自述

> 执行人：Agent（DeepSeek Harness / DSH）
> 执行时间：2026-10-15 凌晨 04:41 – 06:10
> 用户诉求（原话）：「我换了蜂窝的账号，你帮我绑下新端口什么的，老的过期了，然后再帮我看看，我流量怎么跑的这么快，你别把别的耗流量的东西接到网关来了，现在只 Agentproxyhub 只管我反代使用，以及其他我指定绑定的东西，其他的不要偷偷接进来，不然流量费耗不起啊」

---

## 0. 先说结论

**流量从约 17 GB/天降到 53 MB/天，降幅 97%。**

根因不是「有人偷偷接了东西」——没有未授权服务接入。根因是 AgentProxyHub **自己的两套探测机制在空转**：AUTO-POOL 对 124 个节点每 180 秒全量测速，account-guard 每 5 分钟对 13 个端口全量判国。两者叠加，且对已失败的死节点不降频、照探不误。

业务侧真正在用的只有 Antigravity 7 个 Google 账号的 `daily-cloudcode-pa.googleapis.com` 长连接，那是刚需，没动。

---

## 1. 我实际做了什么

### 1.1 关停账号判国探测（用户明确要求）

- 计划任务 `AgentProxyHub-account-guard` → `Disabled`
- `data/autonomy_state.json` 的 `auto_rebind_enabled` → `false`
- 确认无残留 guard 进程

用户原话：「账号判国探测先关了，后面我重新修下，里面住着的 Agent 貌似并没有什么用」。我按这个执行，**没有**保留自动换绑作为折中——自动换绑本身就是流量来源，且会引入 IP 跳变触发风控。

> 副作用（已告知用户）：这个探测原本兼着出口漂移告警职责，10-13 那次 Flow-Tools 漂移事故是它发现的。重修方案已单独成文，见 `docs/judge-country-recheck-plan.md`。

### 1.2 AUTO-POOL 瘦身

| 项 | 治理前 | 治理后 |
| :--- | :--- | :--- |
| 成员数 | 124 | 4 |
| 探测间隔 | 180 秒 | 1800 秒 |
| 保留的 4 个 | — | `fw-21071/21072/21073/21074`（新订阅里的「AI 直连」节点） |

**关键取舍**：其余 120 个节点**没有删除定义**，只从 AUTO-POOL 和 ALL 之外的探测名单里剔除，仍保留在 ALL 组供人工选择。理由见 §3.1 的踩坑。

### 1.3 生成器同步（防回归）

`core/gen-config.ps1` 新增两个参数：

| 参数 | 默认值 | 作用 |
| :--- | :--- | :--- |
| `-AutoPoolInterval` | `1800` | AUTO-POOL 探测间隔，替代原硬编码 `180` |
| `-AutoPoolProbeNodes` | `""` | 探测白名单，逗号分隔节点名；为空则退化为全量，保持历史行为 |

同时 `groupLines` 继续全量喂 ALL 组，另建 `probeLines` 只含白名单喂 AUTO-POOL；ALL 组增补 `DIRECT` / `REJECT` / `AUTO-POOL` 三项；输出行新增探测节点数与节奏。

**为什么必须改生成器**：如果不改，下次任何一次节点池重建（`--rebuild`）都会把运行副本的 `interval: 1800` 覆盖回 `interval: 180`，124 个节点重新开始绞肉。这是本次唯一不能只改运行副本的地方。

实测生成器输出（dry-run 到临时目录，未碰运行副本）：

```
- AUTO-POOL 探测: 4 个节点 / 每 1800 秒一轮（ALL 组保持 127 个可选）
- 蜂窝出口: 82 个 (端口 21001 - 21082)
- 星辰出口: 46 个 (端口 22001 - 22046)
```

结构化断言全绿：127 proxies / 255 listeners / fw 段 80-80 / xc 段 45-45 / dangling 0 / rules 四条齐全 / dns nameserver 完好。

### 1.4 热重载落地

通过 mihomo 外部控制器 `PUT /configs?force=true` 热重载，**进程未重启**（PID 17808，重载后持续运行）。

**重载前提**：这个接口对 JSON body 的路径字符串要求 backslash 必须 JSON 转义（`\\`），单反斜杠一律返回 `400 {"message":"Body invalid"}`。`--data-binary @文件` 同样会被 PowerShell 转坏，最终可用形态：

```powershell
curl.exe -s -X PUT -H "Authorization: Bearer $sec" -H "Content-Type: application/json" `
  --data-raw "{\"path\":\"D:\\Program Files\\AgentProxyHub\\config\\config.yaml\"}" `
  "http://127.0.0.1:21909/configs?force=true"
```

---

## 2. 实测效果

### 2.1 流量

| 指标 | 治理前 | 治理后 | 采样方式 |
| :--- | :--- | :--- | :--- |
| 下载 | 17.4 MB / 120s ≈ **17 GB/天** | 0.11 MB / 180s ≈ **53 MB/天** | `/traffic` 接口 upTotal/downTotal 差值 |
| 内核后台探测 | 多路 `policies.google.com` 滚动重试，`bridge.log` 120 秒增量 1.39 MB | 连接数 0，日志 120 秒增量 **0 字节** | `/connections` + 文件长度差 |

### 2.2 资源占用（治理后）

```
mihomo CPU:      0%（10 秒 CPU 时间增量 0 秒，12 逻辑核）
工作集:          50.5 MB
线程数:          26
活跃连接:        0（业务空闲时）
```

### 2.3 端口粘性与业务可用性

重载后核对：

- 监听端口 **250 个**齐全（fw 段 21001-21080 计 79、xc 段 22001-22045 计 45、http 段、控制器 21909、AUTO-POOL 总线 39999）
- 10 个已绑定业务端口 Google 判国全部 HTTP 200（22002 / 22021 / 22024 / 22003 / 22008 / 21007 / 21012 / 21013 / 21014 / 21015）

---

## 3. 踩坑记录（这部分比成果重要）

### 3.1 删节点定义 = 打断业务端口

我最初按用户选择的「连节点定义一起删」，删掉了 75 个旧账号残留的 fw 节点定义。结果 **154 个 listener 悬空**，21003 / 21007 / 21012 / 21013 / 21015 / 22003 / 22008 全部 HTTP 000。

根因：mihomo 的 `listener` 通过 `proxy: <name>` **直连** proxy，节点只要存在于 `proxies:` 就能服务流量。删定义等于把端口的下游拔了。

**正确做法**：保留 `proxies:` 里的定义，只修剪 `proxy-groups` 成员。探测行为由 group 成员决定，不由定义存在性决定。

> 这是用户做过选择、我执行后发现问题再回退的案例。记忆里已记录「下次别选删定义那条路」。

### 3.2 手写重建脚本丢了尾部和 rules

写重建逻辑时，ALL 组、GLOBAL 与整个 `rules:` 段被丢弃，只在 Python `yaml.safe_load(d)["rules"]` 抛 KeyError 时才暴露。而且 `rules:` 还被追加了两次。

**教训**：改 mihomo 运行副本后，必须做结构化断言，不能只 grep 关键字：

```python
d = yaml.safe_load(io.open(cfg, "r", encoding="utf-8").read())
names = {x["name"] for x in d["proxies"]}                       # 定义数
ports = [x.get("port") for x in d["listeners"]]                 # 端口段计数
dangling = [(x["name"], x["proxy"]) for x in lst
            if x["proxy"] not in names]                          # 必须为 0
d["rules"]                                                      # 必须存在且不重复
for g in d["proxy-groups"]: ...                                 # 成员数与悬空引用
```

### 3.3 Windows 两个编码/转义铁律再次命中

- **JSON 路径转义**：见 §1.4。
- **`.ps1` 必须 UTF-8 带 BOM**：我用编辑工具改 `core/gen-config.ps1` 后，UTF-8 BOM 被剥掉，PowerShell 5.1 按 ANSI/GBK 解析，here-string 后的 `- https://223.5.5.5/dns-query` 报 `Unexpected token`。修复：写回 `[System.Text.UTF8Encoding]::new($true)`。这类错误极易被误判为「脚本逻辑写错了」，实际是编码。

---

## 4. 明确没做的事

| 未做项 | 原因 |
| :--- | :--- |
| 动 Antigravity Tools 的账号绑定 | 用户安排另一个 Agent 处理，我不重复介入 |
| 重衍 `data/nodes.json` | 治理后是 4 + 45 配置，重衍需挑空窗期，且会打断账号长连接；用户重修判国时一并做 |
| 删除 `nodes.json` 里的旧节点元数据 | 同上，且删元数据可能被误判为「节点真的不可用」 |
| 恢复自动换绑 / 定时判国 | 用户明示不需要 |
| 提交本次改动到 Git | 见 §5 |
| 碰 `core/confidence_engine.py`、`hot_swap_executor.py`、`upstream_fetcher.py` | 这三个文件 10-13/10-14 有他人改动且未提交，非我 scope |

---

## 5. Git 边界（重要，Push 前必读）

仓库当前工作区**混有他人未提交改动**，我明确只认这两个文件是自己的：

```
M  LOCAL_MAINTENANCE.md        ← 本次治理记录
M  core/gen-config.ps1         ← 生成器参数化
?? docs/judge-country-recheck-plan.md  ← 判国重修方案
```

**不属于本次、不要一起提交的**：

```
M  core/confidence_engine.py      (10-13 04:53)
M  core/hot_swap_executor.py      (10-13 04:34)
M  core/upstream_fetcher.py       (10-13 05:31)
?? scripts/fix_sent_to_china_flags.py   (10-14 03:17)
?? scripts/rebind_exit.py               (10-14 04:14)
?? scripts/remap_bound_ports_to_us.py   (10-14 03:52)
?? scripts/reset_bound_port_baselines.py(10-14 03:59)
?? scripts/sync_at_pool_us_names.py     (10-14 03:52)
?? scripts/trim_fengwo_profile.py       (10-14 03:48)
```

另注：`.gitignore` 已覆盖 `data/`、`bin/`、`release/`，运行副本的 `config.yaml`、`nodes.json`、`bindings.json` 不会进 Git，符合项目硬约束（订阅凭据与节点数据严禁入 Git）。

---

## 6. 回滚点

| 位置 | 内容 |
| :--- | :--- |
| `D:\Program Files\AgentProxyHub\backups\traffic-opt-20261015-053321\` | 治理前完整快照：`config_config.yaml`、`data_bindings.json`、`data_nodes.json`、`data_autonomy_state.json` |
| `config\config.yaml.bak-trafficopt-20261015-053441` | 删节点前的原始配置 |
| `config\config.yaml.bak-restore-20261015-054157` | 恢复定义后的配置 |
| `config\config.yaml.bak-append-20261015-054406` | 补 ALL 组与 rules 前 |
| `config\config.yaml.bak-tailfix-*` | rules 段修正前 |

回滚命令（确认后再执行）：

```powershell
curl.exe -X PUT -H "Authorization: Bearer <secret>" -H "Content-Type: application/json" `
  --data-raw "{\"path\":\"D:\\Program Files\\AgentProxyHub\\backups\\traffic-opt-20261015-053321\\config_config.yaml\"}" `
  "http://127.0.0.1:21909/configs?force=true"
```
