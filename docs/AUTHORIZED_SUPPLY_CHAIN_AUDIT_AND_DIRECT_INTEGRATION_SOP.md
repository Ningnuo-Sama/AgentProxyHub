# 授权供应链审计、上游归因与直连迁移 SOP

> 版本：2026-10-01
>
> 本文将“黑盒渠道供应链识别”和“独立上游直连迁移”整理为一套可执行的工程方法。适用前提是：目标服务、账户、域名、接口和预算均属于本人或已取得明确授权。
>
> 本文不提供窃取第三方凭据、绕过访问控制、绕过客户端/订阅限制、规避计费或规避供应商熔断的实现。

---

## 1. 目标与边界

### 1.1 目标

- 从已有任务回执、公开价格、正常错误和授权日志中识别可能的供应链关系；
- 核验模型、节点、价格、币种、计费单位和交付质量；
- 使用自己注册、充值获得的上游账户建立最小直连适配器；
- 在不重复扣费、不泄露凭据、不破坏账号/出口粘性的前提下完成灰度迁移；
- 将证据、账单、健康度和回退信息沉淀到 AgentProxyHub 或审计账本。

### 1.2 明确禁止

```yaml
prohibited:
  - 扫描或提取不属于当前授权范围的浏览器凭据
  - 复用他人 Token、Cookie、JWT、API Key
  - 绕过订阅、客户端白名单、套餐权限或访问控制
  - 通过大量非法请求探测计费边界
  - 通过换 IP、轮换账号、伪造客户端规避熔断或风控
  - 未确认任务状态时跨供应商重复提交
  - 将完整 Token、节点密码、签名 URL 写入日志或通知
```

### 1.3 可执行范围

- 被动分析用户提供的日志、回执、媒体 URL、账单和公开文档；
- 对自有域名或明确授权域名执行低频、只读、白名单健康检查；
- 读取用户明确指定的专用浏览器会话中的指定 Origin、指定 Storage Key；
- 使用显式注入的短期测试凭据调用已批准接口；
- 使用自己独立注册和充值的上游账户进行预算内验收。

---

## 2. 总体架构

```text
ScopeRegistry
  ├─ 目标域名、账户、接口白名单、预算、停止条件
  ├─ 供应链证据与价格版本
  └─ 凭据引用，不保存凭据原文

EvidenceCollector
  ├─ HTTP 响应头
  ├─ JSON Pointer 字段
  ├─ 媒体域名与对象哈希
  ├─ 正常错误样本
  └─ 公开价格、账单与任务时间线

FingerprintEngine
  ├─ New API / One API 类
  ├─ Xboard / V2board 类
  ├─ FastAPI / Pydantic / Go / Node 错误族
  └─ OSS / S3 / CDN 交付线索

CapabilityRegistry
  ├─ 模型、时长、画幅、质量、音频、参考图限制
  ├─ 来源与验证时间
  └─ 是否有正式 dry-run/validate 契约

ProviderAdapter
  ├─ 自有上游账户
  ├─ 价格/报价
  ├─ 幂等提交
  ├─ 状态轮询
  └─ 账单对账

AgentProxyHub
  ├─ 出口探活
  ├─ 环境绑定
  ├─ 同区自愈与跨区熔断
  └─ 时序置信度与发布

Notifier
  ├─ 脱敏告警
  ├─ 线索发现
  ├─ 直连验收
  └─ 回退/停止事件
```

AgentProxyHub 作为代理出口、环境绑定和健康度的单一真理源；审计模块只输出候选、证据和状态，不另造节点账本。

---

## 3. 供应链指纹库

> 指纹是线索，不是从属或供货关系的单独证明。

### 3.1 平台类型与常见线索

| 类型 | 常见线索 | 核验方式 | 不能据此断言 |
|---|---|---|---|
| New API / One API 类 | OpenAI 兼容错误信封、模型/分组字段、渠道错误、倍率字段 | 公开文档、自己的前端请求、版本源码 | 同一网关等于同一上游 |
| Xboard / V2board 类 | `/api/v1/user/...` 路由、订阅/节点/流量字段 | 自有控制台请求、正式文档 | 节点数量等于套餐全部权益 |
| 发卡/订单系统 | SKU、订单、支付回调、交付链接 | 自有订单与交付记录 | 主题模板或支付商就是供货商 |
| FastAPI / Pydantic | 422、`detail`、`loc`、`type`、`msg` | 既有错误样本、OpenAPI | 使用 FastAPI 就是转售 |
| Go 服务 | JSON unmarshal、validator 标签、结构字段错误 | 多条错误样本、版本信息 | Go 错误必来自某一具体网关 |
| Node/Express/Nest | 结构化异常、Axios/网关错误信封 | 多信号交叉验证 | 响应头能精确确定实现 |
| OSS/S3/CDN | 对象路径、存储请求 ID、缓存头、签名 URL | 媒体响应、供应商说明 | 存储厂商就是模型供应商 |

### 3.2 HTTP 响应头

建议收集并脱敏：

```text
Server
Via
Date
Content-Type
Cache-Control
ETag
Age
CF-Ray
X-Request-Id
X-Correlation-Id
X-Powered-By
X-Cache
Location
x-amz-request-id
x-oss-request-id
```

解释原则：

- `CF-Ray`：经过 Cloudflare 的线索，不代表业务供应商；
- `Via`、`Age`、`X-Cache`：代理/缓存线索；
- `x-amz-*`、`x-oss-*`：对象存储线索；
- 请求 ID：适合关联日志，不能默认认为上下游 ID 相同；
- `Server: nginx`：只能说明使用了 Nginx。

### 3.3 媒体和静态资源

记录以下非敏感信息：

- API 域名和媒体域名是否不同；
- 域名、路径前缀、扩展名和 Content-Type；
- 任务在不同层级是否出现稳定关联 ID；
- 媒体内容 SHA-256 是否一致；
- 是否为最终对象、预览、转码或缓存副本；
- 签名 URL 的有效期和对象生命周期。

不要自动请求回执中的所有 URL。新域名先进入候选清单，并确认是否在授权范围内。

### 3.4 JSON 深层字段

递归提取并保留 JSON Pointer：

```text
/data/payload/result/task_id
/data/payload/result/content_url
/data/payload/result/provider_task_id
/data/payload/result/billing/charged
/data/payload/result/billing/currency
```

候选字段：

```text
task_id、upstream_task_id、provider_task_id
request_id、created_at、completed_at
content_url、downloadUrl、preview_url、output_url
provider、channel、model
billing、charged、currency、unit、duration
```

外层 `billing` 可能是中转站账单，内层 `billing` 可能是上游声称的费用或配额。两者必须分开记录。

### 3.5 错误指纹

优先分析正常业务已经产生的错误，不要为了获得堆栈而连续制造错误：

```text
invalid_seconds
unsupported_aspect_ratio
validation_error
unknown_model
insufficient_quota
get_channel_failed
No available channel
upstream_timeout
region_unsupported
```

完整 Traceback、内部路径、Token 和 Cookie 不应进入对外报告。

---

## 4. 价格与账单核验

### 4.1 统一计费量纲

```json
{
  "provider": "candidate-upstream",
  "model": "exact-provider-model",
  "duration_seconds": 15,
  "resolution": "720p",
  "quality_tier": "exact-tier",
  "audio": true,
  "currency": "CNY",
  "billing_unit": "task",
  "quoted_amount": "3.50",
  "settled_amount": null,
  "price_version": "observation-time",
  "source": "public-price-table",
  "confidence": "observed"
}
```

金额使用 `Decimal`，不要用浮点数。

### 4.2 加价计算

在型号、时长、质量、币种和结算口径一致时：

```text
有效倍率 = 下游成交价 / 上游合同价
加价率 = 有效倍率 - 1
```

例如 `4.55 / 3.50 = 1.30`，只能证明价格表现出 1.3 倍关系，不能单独证明下游确实以 3.50 采购。

深层 `charged: 0.45` 必须继续核验：

```text
currency 是否 CNY
unit 是每条、每秒、积分还是内部单位
是否为折扣、活动额度、缓存或子步骤费用
是否真实落到账本
是否存在追加扣费、退款或失败计费
```

### 4.3 常见价格陷阱

1. 每秒与每条混用；
2. 最低计费时长高于请求时长；
3. UI 显示 `$`、账本实际使用人民币；
4. 模型倍率、分组倍率、用户倍率重复叠加；
5. 同名模型对应不同速度、音频、水印或优先级；
6. 超时重试造成重复扣费；
7. 充值金额、赠送额度和消费额度不同；
8. 低目录价伴随较高失败率。

```text
有效交付成本 = 同期实际净支出 / 通过业务验收的成片数量
```

---

## 5. 零扣费能力发现与防熔断

### 5.1 不要假设校验一定早于计费

服务端可能采用：

```text
解析 → 参数校验 → 预扣 → 上游创建
解析 → 预扣 → 上游校验 → 失败退款
解析 → 上游创建 → 返回错误 → 异步结算
```

400/422、没有任务 ID、余额暂未变化，都不能单独证明零扣费或未落单。

### 5.2 探测等级

| 等级 | 方法 | 风险 |
|---|---|---|
| P0 | 离线解析已有回执、文档、Schema | 不产生新请求 |
| P1 | 正式文档化的免费元数据、`validate`、`dry_run` 或隔离沙箱 | 依据供应商契约 |
| P2 | 生产创建端点的边界参数 | 可能扣费，不属于零扣费模式 |

未知字段可能被静默忽略；`dry_run` 也必须先核对正式语义。

### 5.3 能力注册表

```text
model
allowed_seconds
allowed_aspect_ratios
max_reference_images
max_reference_video_seconds
supported_audio_modes
face_policy
source
verified_at
verification_method
billing_guarantee
```

既有错误只能形成局部结论，例如：

> 本次版本、模型和渠道返回了仅允许 15 秒的校验结果。

不能扩展成所有渠道、所有版本永远只支持 15 秒。

### 5.4 防熔断协议

```yaml
discovery:
  concurrency_per_origin: 1
  metadata_requests_per_round: 3
  minimum_interval_seconds: 30
  negative_probes_in_production: 0
  automatic_post_retry: false
  cross_origin_redirects: false

stop_immediately_on:
  - get_channel_failed
  - No available channel
  - circuit open
  - unexpected_task_creation
  - unexpected_charge
  - authentication_failure
  - permission_denied

pause_on:
  - rate_limit
  - upstream_5xx
  - network_timeout
```

不通过换 IP、轮换 Token、伪造 UA 或并发请求规避供应商限制。

退避建议：

```text
第一次异常：暂停 60 秒
第二次异常：暂停 5 分钟
第三次异常：结束本轮探测并等待人工确认
```

这是保守默认值，不是对所有部署的安全保证。

---

## 6. 授权鉴权适配

### 6.1 凭据来源原则

推荐顺序：

```text
独立上游 API Key
 → 供应商正式 Token 接口
 → 自己控制的专用浏览器会话
 → 已明确指定的本地配置
 → 离线取证（最后手段）
```

Agent 不应全盘扫描 Chrome、LevelDB、Cookie 或 AppData。凭据应通过短期环境变量、Windows Credential Manager 或专用密钥库注入，日志只记录哈希或别名。

### 6.2 两种 Bearer 适配

```python
import os
import re

TEST_KEY_RE = re.compile(r"^[A-Za-z0-9._~-]{16,256}$")


def make_authorized_headers(kind: str) -> dict[str, str]:
    if kind == "openai_compatible":
        raw = os.environ.get("AUTHORIZED_TEST_API_KEY", "")
        if not TEST_KEY_RE.fullmatch(raw):
            raise RuntimeError("missing or invalid authorized test key")
        return {
            "Authorization": f"Bearer {raw}",
            "Accept": "application/json",
        }

    if kind == "xboard_bearer":
        raw = os.environ.get("AUTHORIZED_XBOARD_TEST_TOKEN", "")
        if raw.lower().startswith("bearer "):
            raw = raw[7:].strip()
        if not TEST_KEY_RE.fullmatch(raw):
            raise RuntimeError("missing or invalid authorized test token")
        return {
            "Authorization": f"Bearer {raw}",
            "Accept": "application/json",
        }

    if kind == "raw_jwt":
        raw = os.environ.get("AUTHORIZED_JWT", "")
        if not re.fullmatch(
            r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", raw
        ):
            raise RuntimeError("missing or invalid authorized JWT")
        return {
            "Authorization": raw,
            "Accept": "application/json",
        }

    raise ValueError(f"unsupported auth kind: {kind}")
```

关键点：JWT 是否带 `Bearer` 由正式接口契约决定，不能凭 JWT 形态猜测。

### 6.3 专用浏览器会话

若必须读取自己的 Web 登录态：

- 使用专用测试 Profile；
- 仅访问明确 Origin；
- 仅读取明确 Storage Key；
- 不遍历所有站点、所有 Key 或 Cookie；
- 不打印原值；
- 读取后只在内存中交给请求适配器；
- 使用完毕后撤销或更换凭据。

Chrome LocalStorage 和 Cookie 不是同一种存储。LevelDB 全盘字符串扫描会捞到旧 Token、其他站点 Token 和删除残留，不能作为标准采集方式。

### 6.4 客户端 YAML

对自己客户端已生成的明文 YAML，优先采用文件监听：

```text
目录变化
 → 防抖
 → 确认写入稳定
 → yaml.safe_load
 → Schema 校验
 → 协议支持检查
 → 节点差异计算
 → 探活
 → 候选池
 → AgentProxyHub 发布
```

使用安全 YAML 解析；不执行 YAML 标签、外部命令或动态代码。节点密码、UUID 和私钥不得写入通知或证据库。

---

## 7. 只读核心探针骨架（Python）

以下探针只访问人工批准的只读接口，不提交视频/图片/聊天任务，不自动跟随跨域跳转，不自动重试高风险错误。

```python
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


class ProbeStopped(RuntimeError):
    pass


def origin(url: str) -> tuple[str, str, int]:
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname:
        raise ValueError("HTTPS origin required")
    if p.username or p.password or p.query or p.fragment:
        raise ValueError("userinfo/query/fragment not allowed")
    return p.scheme, p.hostname.lower(), p.port or 443


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


SAFE_HEADERS = {
    "server", "via", "date", "content-type", "age", "x-cache",
    "cf-ray", "x-request-id", "x-correlation-id",
    "x-amz-request-id", "x-oss-request-id",
}

LINK_KEYS = {
    "content_url", "downloadurl", "preview_url", "output_url", "video_url"
}

VALUE_KEYS = {
    "task_id", "upstream_task_id", "provider_task_id",
    "request_id", "created_at", "completed_at",
    "charged", "currency", "unit", "duration", "seconds",
}

SECRET_KEYS = {
    "authorization", "cookie", "set-cookie", "token",
    "access_token", "refresh_token", "api_key",
    "password", "secret", "uuid", "private_key",
}

STOP_SIGNALS = (
    "get_channel_failed",
    "no available channel",
    "circuit open",
)


def extract_evidence(value, pointer="", depth=0):
    """提取候选证据；不自动访问媒体 URL。"""
    if depth > 20:
        return

    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key)
            escaped = name.replace("~", "~0").replace("/", "~1")
            path = pointer + "/" + escaped
            lower = name.lower()

            if lower in SECRET_KEYS:
                continue

            if lower in LINK_KEYS and isinstance(child, str):
                u = urlsplit(child)
                if u.scheme in {"http", "https"} and u.hostname:
                    yield {
                        "pointer": path,
                        "kind": "media_reference",
                        "host": u.hostname.lower(),
                        "path_sha256": digest(u.path),
                        "has_query": bool(u.query),
                    }

            elif lower in VALUE_KEYS and isinstance(
                child, (str, int, float, bool)
            ):
                if lower.endswith("_id"):
                    yield {
                        "pointer": path,
                        "kind": lower,
                        "value_sha256": digest(str(child)),
                    }
                else:
                    yield {
                        "pointer": path,
                        "kind": lower,
                        "value": child,
                    }

            yield from extract_evidence(child, path, depth + 1)

    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from extract_evidence(child, f"{pointer}/{index}", depth + 1)


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    contract_free: bool
    validation_only: bool = False


class Probe:
    def __init__(self, base_url, endpoints, headers,
                 interval_seconds=30, max_calls=3):
        self.base = base_url.rstrip("/")
        self.expected_origin = origin(self.base)
        self.allowed = {(e.method, e.path): e for e in endpoints}
        self.interval = max(interval_seconds, 0)
        self.max_calls = max_calls
        self.calls = 0
        self.last_call = None
        self.stopped = False
        self.client = httpx.Client(
            headers=headers,
            timeout=httpx.Timeout(15, connect=5),
            follow_redirects=False,
            trust_env=False,
        )

    def close(self):
        self.client.close()

    def call(self, method, path, payload=None):
        method = method.upper()
        if self.stopped:
            raise ProbeStopped("probe already stopped")

        spec = self.allowed.get((method, path))
        if not spec or not spec.contract_free:
            raise ProbeStopped("endpoint not approved as non-billing")
        if payload is not None and not spec.validation_only:
            raise ProbeStopped("payload requires verified validation endpoint")
        if method != "GET" and not spec.validation_only:
            raise ProbeStopped("non-GET disabled outside validation sandbox")
        if self.calls >= self.max_calls:
            raise ProbeStopped("request budget exhausted")
        if not path.startswith("/") or path.startswith("//"):
            raise ProbeStopped("invalid relative path")

        url = self.base + path
        if origin(url) != self.expected_origin:
            raise ProbeStopped("origin mismatch")

        if self.last_call is not None:
            delay = self.interval - (time.monotonic() - self.last_call)
            if delay > 0:
                time.sleep(delay)

        self.calls += 1
        self.last_call = time.monotonic()

        try:
            with self.client.stream(method, url, json=payload) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 1_048_576:
                        raise ProbeStopped("response size limit exceeded")

                text = body.decode("utf-8", errors="replace")
                lower = text.lower()

                if response.status_code in {401, 403, 429}:
                    raise ProbeStopped(
                        f"HTTP {response.status_code}; no auto retry"
                    )
                if response.status_code >= 500:
                    raise ProbeStopped("5xx; no auto retry")
                if 300 <= response.status_code < 400:
                    raise ProbeStopped("redirect requires review")
                if any(signal in lower for signal in STOP_SIGNALS):
                    raise ProbeStopped("channel failure signal")

                obj = json.loads(text)
                return {
                    "status": response.status_code,
                    "headers": {
                        k: v for k, v in response.headers.items()
                        if k.lower() in SAFE_HEADERS
                    },
                    "evidence": list(extract_evidence(obj)),
                }

        except Exception:
            self.stopped = True
            raise
```

`contract_free=True` 必须来自人工核对过的供应商契约；代码无法凭自身判断服务端绝不计费。

---

## 8. 证据链与结论等级

### 8.1 证据等级

| 等级 | 证据 | 允许结论 |
|---|---|---|
| E1 | 媒体域名、路径、框架指纹 | 交付链路出现该服务 |
| E2 | 关联任务 ID、时间、媒体哈希、嵌套提供商字段 | 很可能参与交付 |
| E3 | 自己独立账户的任务、订单、币种账单和回执关联 | 已验证交易链路 |
| E4 | 合同、供应商确认、可核对采购记录 | 已确认供货关系 |

相同媒体哈希可能是缓存或镜像；不同哈希可能是转码或重新封装。

### 8.2 证据事件格式

```json
{
  "observation_id": "local-unique-id",
  "observed_at": "UTC timestamp",
  "source_account_alias": "own-account",
  "source_origin": "https://example.invalid",
  "request_id_hash": "sha256",
  "task_id_hash": "sha256",
  "json_pointer": "/data/payload/billing/charged",
  "observed_value": "0.45",
  "currency": "unknown",
  "evidence_level": "E1",
  "conclusion": "nested charge claim; settlement not verified"
}
```

原始证据和脱敏报告分开保存。OpenViking 只保存结论、方法和脱敏索引，不保存生产 Token、完整节点配置或签名媒体链接。

### 8.3 DoH 的正确定位

DoH 可用于 DNS 解析核验和排查 Fake-IP/解析差异，但不能证明供货关系。域名解析到某 IP 也不能说明两个平台属于同一商业主体。

---

## 9. 独立上游直连适配器

### 9.1 最小接口

```python
class VideoProvider:
    def capabilities(self): ...
    def quote(self, request): ...
    def submit(self, request, idempotency_key): ...
    def get_task(self, provider_task_id): ...
    def get_result(self, provider_task_id): ...
    def reconcile(self, provider_task_id): ...
```

任务记录：

```text
internal_task_id
provider_id
provider_task_id
credential_reference
request_fingerprint
idempotency_key
submission_state
quoted_cost
settled_cost
created_at
```

### 9.2 任务粘性

```text
中转站创建的任务 → 继续在中转站轮询
上游账户创建的新任务 → 在上游轮询
```

不要把中转站任务 ID 当作上游账户下可访问的任务。

### 9.3 超时处理

```text
POST 超时
 → submission_unknown
 → 查询幂等记录/订单/任务
 → 确认未创建后才考虑重试
```

如果供应商不支持幂等键，自定义请求头不能凭空获得幂等保障。禁止通过“再提交一次”确认是否成功。

### 9.4 网络与协议陷阱

- Fake-IP 只在应用正确经过代理内核时有效；绕过代理内核直连会失败；
- HTTPS 应使用域名以保留正确的 Host 和 TLS SNI；
- 不以 `verify=False` 掩盖证书错误；
- `https://IP:port` 必须有匹配 IP 的可信证书或供应商正式方案；
- API Authorization 不得发送到媒体 CDN 域名；
- Referer/UA 按正式接口要求发送，不伪装官方专用客户端绕过权限；
- AnyTLS、Trojan、Shadowsocks 需要分别进行协议字段校验，不能只拼成一个代理 URL。

---

## 10. 代理池迁移与 AgentProxyHub 对接

```text
自有账户拉取节点
 → 权益核验
 → 协议兼容性校验
 → 导入候选池
 → 握手与业务连通测试
 → 多信号区域/风控核验
 → 时序置信度评分
 → AgentProxyHub 发布候选
 → 环境绑定与灰度
```

“美国”或“AI 专属”只是标签。应结合实际出口 IP、多个定位来源、业务成功率和时间序列结果，不把单一服务的区域判定升级为绝对事实。

已有 Profile 不自动跨区改绑。配置热重载、节点可用、账号出口迁移是三个独立事件。

---

## 11. 热切换与通知

### 11.1 视频网关灰度

```text
上游独立注册/充值
 → 能力映射
 → 预算内单任务验收
 → 账单对账
 → 灰度新任务
 → 观察失败率、交付成本和延迟
 → 扩大新任务比例
 → 旧任务继续原路轮询
 → 回退窗口结束
```

不要影子提交两份真实生成任务测试，否则可能双扣费。

### 11.2 通知事件

捕获候选上游特征时：

```text
保存脱敏证据
 → 停止扩散探查
 → 通知：发现候选链路，尚未完成商业确认
```

独立账户直连成功且账单核验后：

```text
通知：直连已验证，可进入灰度
```

通知内容不得包含：

```text
Bearer Token
JWT
API Key
Cookie
节点密码
UUID
私钥
完整签名 URL
```

建议事件：

```json
{
  "event": "authorized_supply_chain_observation",
  "severity": "medium",
  "host": "api.example-owned.com",
  "path": "/health",
  "status": 503,
  "fingerprint": "server:ab12cd34",
  "request_id_hash": "8f4d2a1c",
  "action": "probe_stopped",
  "reason": "repeated_upstream_failure"
}
```

告警规则：

```text
连续 2 次 5xx → 中等级别告警
出现 401/403/429 → 立即停止探针并告警
发现疑似密钥 → 高等级告警、脱敏并停止
重定向到未授权域名 → 高等级告警
进入计费、订单或用户数据路径 → 阻断
```

---

## 12. Agent SOP 状态机

```text
S0 SCOPE
   明确账户、目标、接口白名单、预算和停止条件
   ↓
S1 PASSIVE
   分析已有回执、正常错误、媒体引用和账单
   ↓
S2 CANDIDATES
   输出候选上游，建立 E1/E2 证据，不扩大请求范围
   ↓
S3 PUBLIC_VERIFY
   核对公开销售入口、价格、文档和条款
   ↓
S4 OWN_ACCOUNT
   使用自己的账户注册、充值并取得凭据
   ↓
S5 CAPABILITIES
   优先文档、Schema、正式 validate 或沙箱
   ↓
S6 DIRECT_ACCEPTANCE
   在明确预算内验收直连能力
   ↓
S7 RECONCILE
   对齐币种、单位、账本、成功率、退款政策
   ↓
S8 CANARY
   仅新任务灰度；旧任务保持原路和任务粘性
   ↓
S9 OBSERVE
   监测成本、失败率、延迟、区域和安全事件
   ↓
S10 COMMIT_OR_ROLLBACK
   原子发布或回退，输出脱敏结论
```

任意状态均可进入：

```text
STOP_AUTH       401/403 或账户权限不明
STOP_CHANNEL    渠道不可用、熔断或 No available channel
STOP_BILLING    意外扣费或预算耗尽
STOP_UNKNOWN    创建状态不明，禁止重发
STOP_SECRET     意外凭据暴露
STOP_NOTIFY     命中关键线索，通知并停止扩散
```

---

## 13. 完成标准与检查清单

### 13.1 归因完成

- [ ] 每条证据都有来源、时间和脱敏策略；
- [ ] 结论标注 E1/E2/E3/E4；
- [ ] 线索、技术关联、交易关联、商业确认没有混淆；
- [ ] 没有通过单个 CDN、Header 或错误指纹直接宣布“实锤”。

### 13.2 直连完成

- [ ] 使用自己的上游账户；
- [ ] 凭据来源明确、可撤销；
- [ ] API 与媒体下载链路分离；
- [ ] 任务 ID、幂等键和状态归属正确；
- [ ] 超时不会自动产生跨供应商重复任务。

### 13.3 成本完成

- [ ] 模型、时长、质量和音频档位一致；
- [ ] 币种、计费单位和价格版本明确；
- [ ] 目录价与真实账单分开；
- [ ] 失败、退款、重试和赠送额度已纳入核算；
- [ ] 计算有效交付成本。

### 13.4 代理迁移完成

- [ ] 节点权益与协议字段已核验；
- [ ] 真实握手延迟和业务连通已验证；
- [ ] 区域/风控评分基于多个时序信号；
- [ ] AgentProxyHub 是唯一发布和绑定入口；
- [ ] 有灰度、回退和旧任务保活方案。

### 13.5 安全完成

- [ ] 没有保存 Token、Cookie、节点密码和签名 URL；
- [ ] 探针遇到认证、计费、熔断和未知状态会停止；
- [ ] 通知内容已脱敏；
- [ ] 生产与沙箱凭据分离；
- [ ] 完成后撤销临时凭据或测试账户。

---

## 14. 结论口径

推荐使用以下表达：

- “发现该服务参与媒体交付链路”；
- “存在技术关联，商业供货关系尚未确认”；
- “已用独立账户验证直连能力”；
- “已根据独立账单确认价格和计费单位”；
- “已完成新任务灰度，旧任务仍按原提供商轮询”；
- “已完成 AgentProxyHub 候选发布，尚未自动改绑既有 Profile”。

避免使用没有证据支撑的表达：

- “看到 CDN 就是上游”；
- “返回了 billing 就是实际成本”；
- “400 就一定零扣费”；
- “节点列表全量返回就一定属于当前套餐”；
- “DoH 解析到同 IP 就是同一供应商”；
- “一次直连成功就可以全量切换”。

---

## 15. 本文适用范围声明

本文是授权环境中的审计、对账、供应商选择和系统迁移方法。执行任何真实请求前，应单独确认：

1. 目标域名与接口在授权范围内；
2. 使用的是自己的账户和凭据；
3. 接口是否可能产生费用；
4. 账户、套餐和节点是否允许程序化访问；
5. 失败、超时和重试是否可能重复扣费；
6. 生产切换是否有灰度和回退方案。
