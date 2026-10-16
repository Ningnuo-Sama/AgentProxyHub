param(
    [string]$RootDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$ProfileDir = "$env:APPDATA\com.follow\蜂窝加速器\profiles",
    [string]$FallbackProfileDir = "$env:APPDATA\CellularSeppd\CellularSeppd\profiles",
    [string]$ProfilePath = "",
    [string]$SubscriptionUrl = "",
    [string]$XingchenProfilePath = "",
    [string]$OutDir = "",
    [int]$StartPort = 21001,
    [int]$XingchenStartPort = 22001,
    [string]$ListenAddress = "0.0.0.0",
    [string]$OutboundInterface = "",
    [int]$ControllerPort = 21909,
    [int]$HttpPortOffset = 10000,
    [int]$AutoPoolInterval = 1800,
    # 【治理口径默认值 2026-10-17 t36】默认值必须是治理名单：panel.ps1:1504 调本脚本时不传任何参数
    # （Invoke-Script 的 $extra 默认 @()），因此留空 "" 会让白名单失效、AUTO-POOL 退回 124 个全量成员
    # （= 打开 `--fix` 级别的后台体检流量）。留空时仍可显式传 -AutoPoolProbeNodes "" 恢复历史行为。
    [string]$AutoPoolProbeNodes = "fw-21071,fw-21072,fw-21073,fw-21074",
    # 【映射冻结 P-3 2026-10-17 t36】端口钉定锁表（指纹表：type/server/port/sni，不含凭据）。
    # 锁表内的端口按指纹钉回原节点；指纹在订阅里找不到时 fail-closed：保留原定义、绝不重排。
    [string]$PinFile = "",
    # 【迁移开关】显式指定本开关才会忽略锁表、按订阅序号重排（默认关闭 = 冻结生效）。
    [switch]$AllowRemap,
    # 【凭据落盘脱敏 P2-26 t49，默认开】-OutDir 指向 scratch/暂存目录时，历史上会把生产
    # config.yaml 的真实 password/uuid/secret 原样写进产物（R3-D 安全事故）。默认开启脱敏：
    # 所有**落盘**产物中的 password/uuid/secret 一律替换为 <redacted-*> 占位符，
    # 结构与行数完全保留（mapping-freeze-check.py 的 verify/assert 只依赖 type/server/port/sni，
    # 不依赖凭据值，故复跑不受影响）。确需原值的场景（= 真实部署到 OutDir=$RootDir）用 -NoScrubCredentials 关闭。
    [switch]$NoScrubCredentials
)

$ErrorActionPreference = 'Stop'

if (-not $OutDir) { $OutDir = $RootDir }

# ==============================================================================
# 【P2-26 t49】凭据落盘脱敏：作用于**写文件的那一步**（不是只作用于打印/索引）
# ==============================================================================
# 判据：仅当目标文本中出现与**现网生效凭据**（$RootDir\config\config.yaml 与 config\bridge.json
# 的 secret / 各 proxies[].password / uuid）摘要相等的值时才替换，其余内容一字不动。
# 只算 SHA-256 摘要做比对，绝不打印任何凭据明文。
$script:ScrubCreds = (-not $NoScrubCredentials)
$script:ScrubStats = @{ password = 0; uuid = 0; secret = 0; lines = 0 }
$script:ProdSecretDigest = $null
$script:ProdSecretText = $null
$script:ProdPwDigests = @{}
$script:ProdUuDigests = @{}

function Get-Sha256([string]$text) {
    if ($null -eq $text) { return $null }
    $bytes = [Text.Encoding]::UTF8.GetBytes($text)
    $sb = New-Object Text.StringBuilder
    foreach ($b in (New-Object Security.Cryptography.SHA256Managed).ComputeHash($bytes)) {
        [void]$sb.Append($b.ToString('x2'))
    }
    return $sb.ToString()
}

function Initialize-CredentialScrub {
    <#
    .SYNOPSIS
        采集现网生效凭据的 SHA-256 摘要集合（只算摘要，绝不打印/不输出任何明文）。
    #>
    if (-not $script:ScrubCreds) { return }
    $cfgCands = @((Join-Path $RootDir 'config\config.yaml'), (Join-Path $RootDir 'config.yaml'))
    $secretText = ''
    foreach ($c in $cfgCands) {
        if (-not (Test-Path -LiteralPath $c)) { continue }
        $m = Select-String -LiteralPath $c -Encoding UTF8 -Pattern '^\s*secret\s*:\s*"?([0-9a-fA-F]{8,})"?' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($m) { $secretText = $m.Matches.Groups[1].Value; break }
    }
    if (-not $secretText) {
        foreach ($bj in @((Join-Path $RootDir 'config\bridge.json'), (Join-Path $RootDir 'bridge.json'))) {
            if (-not (Test-Path -LiteralPath $bj)) { continue }
            try {
                $o = Get-Content -LiteralPath $bj -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($o.secret) { $secretText = [string]$o.secret; break }
            } catch { }
        }
    }
    if ($secretText) {
        $script:ProdSecretText = $secretText
        $script:ProdSecretDigest = Get-Sha256 $secretText
    }
    # proxies 的 password/uuid：逐行按 key: value 取摘要（不做整文件转储）
    foreach ($c in $cfgCands) {
        if (-not (Test-Path -LiteralPath $c)) { continue }
        foreach ($line in (Get-Content -LiteralPath $c -Encoding UTF8)) {
            foreach ($key in @('password', 'uuid')) {
                $mm = [regex]::Match($line, ('(?i)\b' + $key + '\s*:\s*"?([^",\s]+)"?'))
                if ($mm.Success) {
                    $d = Get-Sha256 $mm.Groups[1].Value
                    if ($key -eq 'password') { $script:ProdPwDigests[$d] = $true }
                    else { $script:ProdUuDigests[$d] = $true }
                }
            }
        }
        break
    }
}

function Protect-CredentialText([string]$text) {
    <#
    .SYNOPSIS
        把文本中与现网生效凭据值相等的片段替换为占位符（只替换值本体，标点/引号/缩进不动）。
    #>
    if (-not $script:ScrubCreds -or $null -eq $text) { return $text }
    $out = $text
    if ($script:ProdSecretText -and $out.Contains($script:ProdSecretText)) {
        $out = $out.Replace($script:ProdSecretText, '<redacted-secret>')
        $script:ScrubStats['secret'] += ([regex]::Matches($text, [regex]::Escape($script:ProdSecretText))).Count
    }
    # password / uuid：按"key: value"结构定向替换（避免误伤同串的业务字段）
    $out = [regex]::Replace($out, '(?i)(\bpassword\s*:\s*"?)([^",\r\n]+)("?)', {
        param($m)
        $d = Get-Sha256 $m.Groups[2].Value
        if ($script:ProdPwDigests.ContainsKey($d)) {
            $script:ScrubStats['password'] += 1
            return $m.Groups[1].Value + '<redacted-password>' + $m.Groups[3].Value
        }
        return $m.Value
    })
    $out = [regex]::Replace($out, '(?i)(\buuid\s*:\s*"?)([^",\r\n]+)("?)', {
        param($m)
        $d = Get-Sha256 $m.Groups[2].Value
        if ($script:ProdUuDigests.ContainsKey($d)) {
            $script:ScrubStats['uuid'] += 1
            return $m.Groups[1].Value + '<redacted-uuid>' + $m.Groups[3].Value
        }
        return $m.Value
    })
    return $out
}

function Write-ScrubbedText([string]$path, [string]$text) {
    <#
    .SYNOPSIS
        脱敏后写盘：把 Protect-CredentialText 真正作用到"写文件的那一步"。
    #>
    $t = Protect-CredentialText $text
    if ($t -ne $text) { $script:ScrubStats['lines'] += 1 }
    [IO.File]::WriteAllText($path, $t, (New-Object System.Text.UTF8Encoding($false)))
}

Initialize-CredentialScrub

$ErrorActionPreference = 'Stop'

if (-not $OutDir) { $OutDir = $RootDir }
# 1. 出站物理网卡检测：只把桥接上游流量绑定到当前物理出口，避免虚拟网卡 / TUN 循环接管
if ($OutboundInterface) {
    $adapter = Get-NetAdapter -Name $OutboundInterface -ErrorAction Stop
    if ($adapter.Status -ne 'Up') { throw "指定的出站网卡未连接: $OutboundInterface" }
} else {
    $physicalIds = @(Get-NetAdapter -Physical -ErrorAction Stop |
        Where-Object Status -eq 'Up' | ForEach-Object ifIndex)
    $route = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
        Where-Object { $_.ifIndex -in $physicalIds -and $_.NextHop -ne '0.0.0.0' } |
        Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1
    if (-not $route) { throw '没有找到可用的物理默认路由，请用 -OutboundInterface 指定网卡' }
    $OutboundInterface = $route.InterfaceAlias
}

# 2. Clash flow map 感知切分
function Split-FlowMap([string]$inner) {
    $parts = New-Object System.Collections.Generic.List[string]
    $cur = ''
    $quote = $null
    $depth = 0
    foreach ($ch in $inner.ToCharArray()) {
        if ($quote) {
            if ($ch -eq $quote) { $quote = $null } else { $cur += $ch }
            continue
        }
        if ($ch -eq "'" -or $ch -eq '"') { $quote = $ch; continue }
        if ($ch -eq '[' -or $ch -eq '{') { $depth++; $cur += $ch; continue }
        if ($ch -eq ']' -or $ch -eq '}') { $depth--; $cur += $ch; continue }
        if ($ch -eq ',' -and $depth -eq 0) { $parts.Add($cur); $cur = ''; continue }
        $cur += $ch
    }
    if ($cur.Trim()) { $parts.Add($cur) }
    return $parts
}

# 3. 从 YAML 文件解析有效节点列表
function Get-ProxyNodes([string]$path, [string]$airportName) {
    $nodes = New-Object System.Collections.Generic.List[object]
    if (-not (Test-Path -LiteralPath $path)) { return $nodes }
    $lines = Get-Content -LiteralPath $path -Encoding UTF8
    foreach ($line in $lines) {
        if ($line -notmatch '^\s*-\s*\{(.+)\}\s*$') { continue }
        $fields = [ordered]@{}
        foreach ($p in (Split-FlowMap $Matches[1])) {
            $i = $p.IndexOf(':')
            if ($i -lt 0) { continue }
            $k = $p.Substring(0, $i).Trim()
            $v = $p.Substring($i + 1).Trim()
            if ($v.Length -ge 2) {
                if (($v.StartsWith("'") -and $v.EndsWith("'")) -or ($v.StartsWith('"') -and $v.EndsWith('"'))) {
                    $v = $v.Substring(1, $v.Length - 2)
                }
            }
            if ($k) { $fields[$k] = $v }
        }
        if (-not $fields.Contains('type')) { continue }
        if ($fields['type'] -notin @('anytls', 'trojan', 'vless', 'vmess', 'ss', 'ss2022', 'hysteria2', 'tuic')) { continue }
        if (-not $fields.Contains('server') -or -not $fields.Contains('port')) { continue }
        
        $orig = if ($fields.Contains('name')) { $fields['name'] } else { '' }
        # 过滤掉宣传、到期提示等虚假节点
        # 过滤掉宣传、到期提示等虚假节点
        # 【2026-10-17 t36 扩展】原正则漏掉「距离下次重置剩余：N 天」与「电报：@xxx」：
        # 前者能通过旧正则 ⇒ 会占掉一个端口号 ⇒ 其后全部节点顺移一位（铁证：data\nodes.json 里
        # fw-21001 的 orig 就是「距离下次重置剩余：23 天」）。故补齐占位/宣传词。
        if ($orig -match '剩余流量|套餐到期|官网|网址|下载|交流群|公告|国内访问|距离下次重置|重置剩余|电报|@|剩余|到期|订阅|客服|TG|群') { continue }
        
        $nodes.Add([pscustomobject]@{
            Fields   = $fields
            Server   = $fields['server']
            Port     = [int]$fields['port']
            Type     = $fields['type']
            OrigName = $orig
            Airport  = $airportName
        })
    }
    return $nodes
}

# 4. 获取主上游 Profile（优先显式指定，其次订阅下载，再次本地目录自动探测）
$fwProfileFile = $null
if ($SubscriptionUrl) {
    Write-Output "正在从通用订阅下载配置: $SubscriptionUrl ..."
    $subTmp = Join-Path $env:TEMP "aphub_sub_$(Get-Random).yaml"
    & curl.exe -s -L --max-time 30 --ssl-no-revoke -o $subTmp $SubscriptionUrl
    if ((Test-Path -LiteralPath $subTmp) -and (Get-Item -LiteralPath $subTmp).Length -gt 500) {
        $fwProfileFile = Get-Item -LiteralPath $subTmp
    } else {
        Write-Warning "通用订阅下载失败，回退本地查找"
    }
}

if (-not $fwProfileFile) {
    if ($ProfilePath) {
        if (Test-Path -LiteralPath $ProfilePath) { $fwProfileFile = Get-Item -LiteralPath $ProfilePath }
    } else {
        $candidates = New-Object System.Collections.Generic.List[object]
        foreach ($dir in @($ProfileDir, $FallbackProfileDir)) {
            if (-not (Test-Path -LiteralPath $dir)) { continue }
            $cand = Get-ChildItem -LiteralPath $dir -Filter *.yaml -File -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -notmatch '\.bak|\.backup' }
            foreach ($c in $cand) { $candidates.Add($c) }
        }
        if ($candidates.Count -gt 0) {
            $fwProfileFile = $candidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        }
    }
}

$fwNodes = @()
if ($fwProfileFile) {
    $allFw = Get-ProxyNodes $fwProfileFile.FullName '蜂窝'
    $seenFw = @{}
    foreach ($n in $allFw) {
        $k = "$($n.Server):$($n.Port)"
        if (-not $seenFw.ContainsKey($k)) {
            $seenFw[$k] = $true
            $fwNodes += $n
        }
    }
}

# 5. 获取星辰 Profile
if (-not $XingchenProfilePath) {
    $xcCandidates = @(
        (Join-Path $RootDir 'config\xingchen_profile.yaml'),
        (Join-Path $RootDir 'data\xingchen_profile.yaml'),
        (Join-Path $RootDir 'xingchen_profile.yaml'),
        'D:\Program Files\AgentProxyHub\config\xingchen_profile.yaml',
        'D:\Program Files\FengWoBridge\xingchen_profile.yaml'
    )
    foreach ($xcp in $xcCandidates) {
        if (Test-Path -LiteralPath $xcp) {
            $XingchenProfilePath = $xcp
            break
        }
    }
}

$xcNodes = @()
if ($XingchenProfilePath -and (Test-Path -LiteralPath $XingchenProfilePath)) {
    $allXc = Get-ProxyNodes $XingchenProfilePath '星辰'
    $seenXc = @{}
    foreach ($n in $allXc) {
        $k = "$($n.Server):$($n.Port)"
        if (-not $seenXc.ContainsKey($k)) {
            $seenXc[$k] = $true
            $xcNodes += $n
        }
    }
}

Write-Output "节点解析结果: 蜂窝出口 $($fwNodes.Count) 个 | 星辰出口 $($xcNodes.Count) 个"

$proxyLines = New-Object System.Collections.Generic.List[string]
$listenerLines = New-Object System.Collections.Generic.List[string]
$groupLines = New-Object System.Collections.Generic.List[string]
$probeLines = New-Object System.Collections.Generic.List[string]
$mapping = New-Object System.Collections.Generic.List[object]

# 省流量探测名单（2026-10-15）：
# AUTO-POOL 的 url-test 会对每个成员每轮发一次 generate_204，124 个成员 × 180s
# 的轮询是后台流量主因。默认只让「AI 直连」节点进探测名单，其余节点仍需留在
# ALL 里供人工选择，但不参与自动体检。
# 逗号分隔的节点名（如 "fw-21071,fw-21072,fw-21073,fw-21074"）；留空时退化为
# 全部节点，保持历史行为。
$probeAllow = @()
if ($AutoPoolProbeNodes -and $AutoPoolProbeNodes.Trim().Length -gt 0) {
    $probeAllow = $AutoPoolProbeNodes.Split(',') |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -ne '' }
}

# ===== 映射冻结（P-1 + P-3）2026-10-17 t36 落地 =====
# 端口号不再单纯等于订阅序号：先按锁表把「在册绑定口」钉回原节点，其余口再按订阅顺序填充。
# 锁表为**指纹表**（type/server/port/sni），不含任何凭据字段；无锁表时退化为历史行为并告警。
$pinPath = if ($PinFile) { $PinFile } else { Join-Path $RootDir 'data\port_map_lock.json' }
$pinFw = @{}
$pinXc = @{}
if ($AllowRemap) {
    Write-Warning "已指定 -AllowRemap：忽略锁表，按订阅序号重新分配（映射冻结被显式关闭）"
} elseif (Test-Path -LiteralPath $pinPath) {
    try {
        $pinJson = Get-Content -LiteralPath $pinPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($k in $pinJson.ports.PSObject.Properties.Name) {
            $pk = [int]$k
            if ($pk -ge $XingchenStartPort) { $pinXc[$pk] = $pinJson.ports.$k } else { $pinFw[$pk] = $pinJson.ports.$k }
        }
        Write-Output "映射冻结: 锁表 $pinPath 已加载（蜂窝 $($pinFw.Count) 口 / 星辰 $($pinXc.Count) 口）"
    } catch {
        Write-Warning "锁表 $pinPath 解析失败 ⇒ 退化为订阅序号分配（映射冻结未生效）：$_"
    }
} else {
    Write-Warning "未找到锁表 $pinPath ⇒ 退化为订阅序号分配（映射冻结未生效；请先补齐锁表）"
}

function Test-NodePinned([object]$node, [object]$want) {
    if ($null -eq $want -or $null -eq $node) { return $false }
    if (([string]$node.Type)   -ne ([string]$want.type))   { return $false }
    if (([string]$node.Server) -ne ([string]$want.server)) { return $false }
    if (([string]$node.Port)   -ne ([string]$want.port))   { return $false }
    if (([string]$node.Fields['sni']) -ne ([string]$want.sni)) { return $false }
    return $true
}

function Get-ExistingProxyLine([string]$proxyName) {
    # 锁表节点已从订阅消失时的 fail-closed 回退：从现有 config.yaml 按名取回原定义（只取 1 行，不做转储）
    $cands = @((Join-Path $OutDir 'config\config.yaml'), (Join-Path $RootDir 'config\config.yaml'))
    foreach ($cand in $cands) {
        if (-not (Test-Path -LiteralPath $cand)) { continue }
        $hit = Select-String -LiteralPath $cand -Encoding UTF8 -Pattern ('^\s*-\s*\{\s*name:\s*' + [regex]::Escape($proxyName) + '\s*,') | Select-Object -First 1
        if ($hit) { return $hit.Line }
    }
    return $null
}

function Build-PortPlan([object[]]$nodes, [hashtable]$pin, [int]$startPort, [int]$maxPort) {
    # 锁表口（pinned）：只接受**同指纹**节点，并**保留锁表里的原 proxy 名**（保证 port→proxy 逐条不变）；
    # 指纹在订阅里找不到 ⇒ Node=$null，由调用方 fail-closed 保留原定义，**绝不**用别的节点顶替。
    # 非锁表口：按订阅顺序取下一个未使用节点，沿用历史命名 fw-<port> / xc-<port>。
    $ordered = New-Object System.Collections.Generic.List[object]
    $used = New-Object System.Collections.Generic.HashSet[int]
    $cursor = 0
    for ($p = $startPort; $p -le $maxPort; $p++) {
        if ($pin.ContainsKey($p)) {
            $picked = -1
            for ($i = 0; $i -lt $nodes.Count; $i++) {
                if ($used.Contains($i)) { continue }
                if (Test-NodePinned $nodes[$i] $pin[$p]) { $picked = $i; break }
            }
            $lockName = [string]$pin[$p].name
            if ($picked -ge 0) {
                [void]$used.Add($picked)
                $ordered.Add([pscustomobject]@{ Port = $p; Node = $nodes[$picked]; Pinned = $true; Matched = $true; LockName = $lockName })
            } else {
                $ordered.Add([pscustomobject]@{ Port = $p; Node = $null; Pinned = $true; Matched = $false; LockName = $lockName })
            }
        } else {
            while ($cursor -lt $nodes.Count -and $used.Contains($cursor)) { $cursor++ }
            if ($cursor -lt $nodes.Count) {
                [void]$used.Add($cursor)
                $ordered.Add([pscustomobject]@{ Port = $p; Node = $nodes[$cursor]; Pinned = $false; Matched = $false; LockName = '' })
                $cursor++
            } else {
                $ordered.Add([pscustomobject]@{ Port = $p; Node = $null; Pinned = $false; Matched = $false; LockName = '' })
            }
        }
    }
    $unassigned = @()
    for ($i = 0; $i -lt $nodes.Count; $i++) { if (-not $used.Contains($i)) { $unassigned += $nodes[$i] } }
    return @{ Ordered = $ordered; Dropped = $unassigned }
}

$fwPlan = Build-PortPlan $fwNodes $pinFw $StartPort 21080
$xcPlan = Build-PortPlan $xcNodes $pinXc $XingchenStartPort 22045
if ($fwPlan.Dropped.Count -gt 0) {
    Write-Warning "[超段/未分配] 蜂窝段 $StartPort-21080：$($fwPlan.Dropped.Count) 个订阅节点未进入段内（原因：段容量 80 不足 与/或 锁表口保留原定义占住了槽位）"
}
if ($xcPlan.Dropped.Count -gt 0) {
    Write-Warning "[超段/未分配] 星辰段 $XingchenStartPort-22045：$($xcPlan.Dropped.Count) 个订阅节点未进入段内（原因同上）"
}
$fwPinHit = @($fwPlan.Ordered | Where-Object { $_.Matched }).Count
$xcPinHit = @($xcPlan.Ordered | Where-Object { $_.Matched }).Count
$fwPinMiss = @($fwPlan.Ordered | Where-Object { $_.Pinned -and (-not $_.Matched) }).Count
$xcPinMiss = @($xcPlan.Ordered | Where-Object { $_.Pinned -and (-not $_.Matched) }).Count
Write-Output "映射冻结: 锁表命中 蜂窝 $fwPinHit/$($pinFw.Count) 口 / 星辰 $xcPinHit/$($pinXc.Count) 口"
if (($fwPinMiss + $xcPinMiss) -gt 0) {
    Write-Warning "映射冻结: $($fwPinMiss + $xcPinMiss) 个锁表口在订阅里已找不到同指纹 ⇒ 保留原定义（fail-closed，绝不重排）。如需改用新节点，必须显式迁移（重新生成锁表 + -AllowRemap）。"
}

# 已输出过的 proxy 名（锁表允许一个 proxy 服务多个端口，避免重复定义）
$emittedProxy = New-Object System.Collections.Generic.HashSet[string]
$proxiesTotal = 0

# 生成蜂窝出口映射 (21001 起始；锁表口按指纹钉定并保留原名，其余口按订阅顺序填充)
foreach ($item in $fwPlan.Ordered) {
    $port = $item.Port
    $n = $item.Node
    if ($item.Pinned) { $name = $item.LockName } else { $name = "fw-$port" }
    if ($null -ne $n) {
        $n.Fields['name'] = $name
        if (-not $n.Fields.Contains('udp')) { $n.Fields['udp'] = 'true' }
        if ($n.Fields.Contains('sni') -and -not $n.Fields.Contains('skip-cert-verify')) {
            $n.Fields['skip-cert-verify'] = 'true'
        }
        $pairs = foreach ($k in $n.Fields.Keys) { "$k`: $($n.Fields[$k])" }
        if (-not $emittedProxy.Contains($name)) {
            [void]$emittedProxy.Add($name)
            $proxyLines.Add("    - { " + ($pairs -join ', ') + " }")
            $proxiesTotal++
        }
        $nType = $n.Type; $nServer = $n.Server; $nServerPort = $n.Port; $nOrig = $n.OrigName
    } else {
        $oldLine = Get-ExistingProxyLine $name
        if (-not $oldLine) {
            Write-Warning "口 $name（端口 $port）既无订阅节点也无原定义可回退：跳过该口（会产生缺口）"
            continue
        }
        if (-not $emittedProxy.Contains($name)) {
            [void]$emittedProxy.Add($name)
            $proxyLines.Add($oldLine)
            $proxiesTotal++
        }
        if ($item.Pinned) { Write-Warning "锁表口 $name（端口 $port）的节点已从订阅消失：保留原定义（fail-closed，不重排）" }
        $nType = 'pinned-missing'; $nServer = '-'; $nServerPort = 0; $nOrig = '(锁表节点已消失，保留原定义)'
    }

    $listenerLines.Add("    - name: in-$port")
    $listenerLines.Add("      type: socks")
    $listenerLines.Add("      port: $port")
    $listenerLines.Add("      listen: $ListenAddress")
    $listenerLines.Add("      proxy: $name")
    $listenerLines.Add("      udp: true")
    $groupLines.Add("        - $name")
    if ($probeAllow.Count -eq 0 -or $probeAllow -contains $name) {
        $probeLines.Add("        - $name")
    }

    $httpPort = $null
    if ($HttpPortOffset -gt 0) {
        $httpPort = $port + $HttpPortOffset
        $listenerLines.Add("    - name: in-http-$port")
        $listenerLines.Add("      type: http")
        $listenerLines.Add("      port: $httpPort")
        $listenerLines.Add("      listen: $ListenAddress")
        $listenerLines.Add("      proxy: $name")
    }

    $mapping.Add([pscustomobject]@{
        ListenPort = $port
        HttpPort   = $httpPort
        ProxyName  = $name
        Airport    = '蜂窝'
        Type       = $nType
        Server     = $nServer
        ServerPort = $nServerPort
        OrigName   = $nOrig
    })
}

# 生成星辰出口映射 (22001 起始；锁表口按指纹钉定并保留原名，其余口按订阅顺序填充)
foreach ($item in $xcPlan.Ordered) {
    $port = $item.Port
    $n = $item.Node
    if ($item.Pinned) { $name = $item.LockName } else { $name = "xc-$port" }
    if ($null -ne $n) {
        $n.Fields['name'] = $name
        if (-not $n.Fields.Contains('udp')) { $n.Fields['udp'] = 'true' }
        if ($n.Fields.Contains('sni') -and -not $n.Fields.Contains('skip-cert-verify')) {
            $n.Fields['skip-cert-verify'] = 'true'
        }
        $pairs = foreach ($k in $n.Fields.Keys) { "$k`: $($n.Fields[$k])" }
        if (-not $emittedProxy.Contains($name)) {
            [void]$emittedProxy.Add($name)
            $proxyLines.Add("    - { " + ($pairs -join ', ') + " }")
            $proxiesTotal++
        }
        $nType = $n.Type; $nServer = $n.Server; $nServerPort = $n.Port; $nOrig = $n.OrigName
    } else {
        $oldLine = Get-ExistingProxyLine $name
        if (-not $oldLine) {
            Write-Warning "口 $name（端口 $port）既无订阅节点也无原定义可回退：跳过该口（会产生缺口）"
            continue
        }
        if (-not $emittedProxy.Contains($name)) {
            [void]$emittedProxy.Add($name)
            $proxyLines.Add($oldLine)
            $proxiesTotal++
        }
        if ($item.Pinned) { Write-Warning "锁表口 $name（端口 $port）的节点已从订阅消失：保留原定义（fail-closed，不重排）" }
        $nType = 'pinned-missing'; $nServer = '-'; $nServerPort = 0; $nOrig = '(锁表节点已消失，保留原定义)'
    }

    $listenerLines.Add("    - name: in-$port")
    $listenerLines.Add("      type: socks")
    $listenerLines.Add("      port: $port")
    $listenerLines.Add("      listen: $ListenAddress")
    $listenerLines.Add("      proxy: $name")
    $listenerLines.Add("      udp: true")
    $groupLines.Add("        - $name")
    if ($probeAllow.Count -eq 0 -or $probeAllow -contains $name) {
        $probeLines.Add("        - $name")
    }

    $httpPort = $null
    if ($HttpPortOffset -gt 0) {
        $httpPort = $port + $HttpPortOffset
        $listenerLines.Add("    - name: in-http-$port")
        $listenerLines.Add("      type: http")
        $listenerLines.Add("      port: $httpPort")
        $listenerLines.Add("      listen: $ListenAddress")
        $listenerLines.Add("      proxy: $name")
    }

    $mapping.Add([pscustomobject]@{
        ListenPort = $port
        HttpPort   = $httpPort
        ProxyName  = $name
        Airport    = '星辰'
        Type       = $nType
        Server     = $nServer
        ServerPort = $nServerPort
        OrigName   = $nOrig
    })
}
# 保持稳定的控制器密钥
$secret = ''
$candidatesForSecret = @(
    (Join-Path $OutDir 'config\config.yaml'),
    (Join-Path $OutDir 'config.yaml'),
    (Join-Path $RootDir 'config\bridge.json'),
    (Join-Path $RootDir 'bridge.json'),
    'D:\Program Files\FengWoBridge\bridge.json'
)
foreach ($cf in $candidatesForSecret) {
    if (Test-Path -LiteralPath $cf) {
        if ($cf.EndsWith('.json')) {
            try {
                $bj = Get-Content -LiteralPath $cf -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($bj.secret) { $secret = $bj.secret; break }
            } catch { }
        } elseif ($cf.EndsWith('.yaml')) {
            $m = Select-String -LiteralPath $cf -Pattern '^secret: "([0-9a-fA-F]+)"' -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($m) { $secret = $m.Matches.Groups[1].Value; break }
        }
    }
}
if (-not $secret) {
    $secret = -join ((1..24) | ForEach-Object { '{0:x}' -f (Get-Random -Minimum 0 -Maximum 16) })
}

# 组装完整的 mihomo 配置
$header = @"
# ============================================================
# AgentProxyHub 多出口调度配置 (自动生成)
# 生成时间     : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
# 蜂窝出口数量 : $($fwNodes.Count)  端口范围: $StartPort - $($StartPort + $fwNodes.Count - 1)
# 星辰出口数量 : $($xcNodes.Count)  端口范围: $XingchenStartPort - $($XingchenStartPort + $xcNodes.Count - 1)
# 智能分流总线 : 39999 (手机/局域网无感接入)
# ============================================================
mixed-port: 0
port: 0
socks-port: 0
redir-port: 0
tproxy-port: 0
allow-lan: true
bind-address: "*"
interface-name: "$OutboundInterface"
mode: rule
log-level: warning
ipv6: false
unified-delay: true
tcp-concurrent: true
find-process-mode: off
external-controller: 127.0.0.1:$ControllerPort
secret: "$secret"
profile:
    store-selected: false
    store-fake-ip: false
dns:
    enable: true
    ipv6: false
    enhanced-mode: normal
    use-hosts: false
    nameserver:
        - https://223.5.5.5/dns-query
        - https://doh.pub/dns-query
    proxy-server-nameserver:
        - https://223.5.5.5/dns-query
        - https://doh.pub/dns-query
proxies:
$($proxyLines -join "`r`n")
listeners:
    - name: in-rule-phone
      type: mixed
      port: 39999
      listen: $ListenAddress
      udp: true
$($listenerLines -join "`r`n")
proxy-groups:
    - name: AUTO-POOL
      type: url-test
      url: https://www.gstatic.com/generate_204
      interval: $AutoPoolInterval
      tolerance: 50
      proxies:
$((($probeLines | Select-Object -Unique) -join "`r`n"))
    - name: ALL
      type: select
      proxies:
        - DIRECT
        - REJECT
        - AUTO-POOL
$((($groupLines | Select-Object -Unique) -join "`r`n"))
rules:
    - GEOIP,lan,DIRECT,no-resolve
    - GEOSITE,cn,DIRECT
    - GEOIP,cn,DIRECT
    - MATCH,AUTO-POOL
"@

# 写入配置文件（同时写入 config/ 与根目录以保证各种启动模式兼容）
$configDirs = @((Join-Path $OutDir 'config'), $OutDir)
foreach ($cd in $configDirs) {
    if (-not (Test-Path -LiteralPath $cd)) { [void](New-Item -ItemType Directory -Path $cd -Force) }
    Write-ScrubbedText -Path (Join-Path $cd 'config.yaml') -Text $header
}

# 写入映射数据
$dataDirs = @((Join-Path $OutDir 'data'), $OutDir)
foreach ($dd in $dataDirs) {
    if (-not (Test-Path -LiteralPath $dd)) { [void](New-Item -ItemType Directory -Path $dd -Force) }
    $mapping | Export-Csv -LiteralPath (Join-Path $dd 'port_map.csv') -NoTypeInformation -Encoding UTF8
    $mapping | Export-Csv -LiteralPath (Join-Path $dd '端口对照.csv') -NoTypeInformation -Encoding UTF8

    $mapping | ForEach-Object { "127.0.0.1`:$($_.ListenPort)" } |
        Set-Content -LiteralPath (Join-Path $dd 'P1-智能解析粘贴.txt') -Encoding UTF8

    $mapping | ForEach-Object { "socks5://127.0.0.1`:$($_.ListenPort)" } |
        Set-Content -LiteralPath (Join-Path $dd '批量导入-socks5.txt') -Encoding UTF8

    $httpRows = $mapping | Where-Object { $_.HttpPort }
    if ($httpRows) {
        $httpRows | ForEach-Object { "http://127.0.0.1`:$($_.HttpPort)" } |
            Set-Content -LiteralPath (Join-Path $dd '批量导入-http.txt') -Encoding UTF8
    }
}

# 生成 bridge.json 元数据
$bridgeInfo = [pscustomobject]@{
    profilePath       = if ($fwProfileFile) { $fwProfileFile.FullName } else { '' }
    xingchenProfile   = $XingchenProfilePath
    secret            = $secret
    controller        = "127.0.0.1:$ControllerPort"
    fwCount           = $fwNodes.Count
    xcCount           = $xcNodes.Count
    totalCount        = $mapping.Count
    outboundInterface = $OutboundInterface
    generatedAt       = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
}
$bridgeJsonText = $bridgeInfo | ConvertTo-Json
foreach ($bd in @((Join-Path $OutDir 'config'), $OutDir)) {
    Write-ScrubbedText -Path (Join-Path $bd 'bridge.json') -Text $bridgeJsonText
}

Write-Output "✅ AgentProxyHub 端口池与配置生成完成："
Write-Output "   - 蜂窝出口: 有效节点 $($fwNodes.Count) 个 / 段内 $($fwPlan.Ordered.Count) 口（超段丢弃 $($fwPlan.Dropped.Count) 个；端口 $StartPort - 21080）"
Write-Output "   - 星辰出口: 有效节点 $($xcNodes.Count) 个 / 段内 $($xcPlan.Ordered.Count) 口（超段丢弃 $($xcPlan.Dropped.Count) 个；端口 $XingchenStartPort - 22045）"
Write-Output "   - 总计出口: $($mapping.Count) 个"
Write-Output "   - 映射冻结: 锁表命中 蜂窝 $fwPinHit/$($pinFw.Count) 口 / 星辰 $xcPinHit/$($pinXc.Count) 口（未命中按订阅顺序填充）"
Write-Output "   - AUTO-POOL 探测: $((@($probeLines | Select-Object -Unique)).Count) 个节点 / 每 $AutoPoolInterval 秒一轮（ALL 组保持 $((@($groupLines | Select-Object -Unique)).Count) 个可选）"
Write-Output "   - 控制器  : 127.0.0.1:$ControllerPort"
Write-Output "   - 配置文件: $(Join-Path $OutDir 'config\config.yaml')"

# ==============================================================================
# 【P2-26 t49】落盘脱敏统计（只报计数，不报任何值）
# ==============================================================================
if ($script:ScrubCreds) {
    Write-Output "   - 凭据脱敏: 已开启（password=$($script:ScrubStats['password']) / uuid=$($script:ScrubStats['uuid']) / secret=$($script:ScrubStats['secret']) 处替换，涉及 $($script:ScrubStats['lines']) 个落盘文件）"
    if ($script:ScrubStats['password'] -eq 0 -and $script:ScrubStats['uuid'] -eq 0 -and $script:ScrubStats['secret'] -eq 0) {
        Write-Output "     （本目录未发现与现网生效凭据相等的值，无需替换）"
    }
} else {
    Write-Output "   - 凭据脱敏: 已关闭（-NoScrubCredentials）——仅用于真实部署到 RootDir 的场景"
}
