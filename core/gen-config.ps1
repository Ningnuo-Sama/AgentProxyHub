# ==============================================================================
# AgentProxyHub 端口池与 mihomo 配置生成器 (Port Pool & Config Generator)
# ==============================================================================
# 功能：从通用订阅 / 本地 Clash Profile 生成「一节点一独立本地 SOCKS5/HTTP 端口」的 mihomo 配置
# 端口分配规范：
#   - 蜂窝出口: 21001-21080 (HTTP 31001-31080)
#   - 星辰出口: 22001-22045 (HTTP 32001-32045)
#   - 智能规则总线: 39999 (混合 HTTP/SOCKS5，局域网与手机免软件自适应)
#   - 外部控制器: 127.0.0.1:21909

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
    [int]$HttpPortOffset = 10000
)

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
        if ($orig -match '剩余流量|套餐到期|官网|网址|下载|交流群|公告|国内访问') { continue }
        
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
$mapping = New-Object System.Collections.Generic.List[object]

# 生成蜂窝出口映射 (21001 起始，严格对齐原有分配)
$port = $StartPort
foreach ($n in $fwNodes) {
    $name = "fw-$port"
    $n.Fields['name'] = $name
    if (-not $n.Fields.Contains('udp')) { $n.Fields['udp'] = 'true' }
    if ($n.Fields.Contains('sni') -and -not $n.Fields.Contains('skip-cert-verify')) {
        $n.Fields['skip-cert-verify'] = 'true'
    }
    $pairs = foreach ($k in $n.Fields.Keys) { "$k`: $($n.Fields[$k])" }
    $proxyLines.Add("    - { " + ($pairs -join ', ') + " }")
    
    $listenerLines.Add("    - name: in-$port")
    $listenerLines.Add("      type: socks")
    $listenerLines.Add("      port: $port")
    $listenerLines.Add("      listen: $ListenAddress")
    $listenerLines.Add("      proxy: $name")
    $listenerLines.Add("      udp: true")
    $groupLines.Add("        - $name")
    
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
        Type       = $n.Type
        Server     = $n.Server
        ServerPort = $n.Port
        OrigName   = $n.OrigName
    })
    $port++
}

# 生成星辰出口映射 (22001 起始，严格对齐原有分配)
$xcPort = $XingchenStartPort
foreach ($n in $xcNodes) {
    $name = "xc-$xcPort"
    $n.Fields['name'] = $name
    if (-not $n.Fields.Contains('udp')) { $n.Fields['udp'] = 'true' }
    if ($n.Fields.Contains('sni') -and -not $n.Fields.Contains('skip-cert-verify')) {
        $n.Fields['skip-cert-verify'] = 'true'
    }
    $pairs = foreach ($k in $n.Fields.Keys) { "$k`: $($n.Fields[$k])" }
    $proxyLines.Add("    - { " + ($pairs -join ', ') + " }")
    
    $listenerLines.Add("    - name: in-$xcPort")
    $listenerLines.Add("      type: socks")
    $listenerLines.Add("      port: $xcPort")
    $listenerLines.Add("      listen: $ListenAddress")
    $listenerLines.Add("      proxy: $name")
    $listenerLines.Add("      udp: true")
    $groupLines.Add("        - $name")
    
    $httpPort = $null
    if ($HttpPortOffset -gt 0) {
        $httpPort = $xcPort + $HttpPortOffset
        $listenerLines.Add("    - name: in-http-$xcPort")
        $listenerLines.Add("      type: http")
        $listenerLines.Add("      port: $httpPort")
        $listenerLines.Add("      listen: $ListenAddress")
        $listenerLines.Add("      proxy: $name")
    }
    
    $mapping.Add([pscustomobject]@{
        ListenPort = $xcPort
        HttpPort   = $httpPort
        ProxyName  = $name
        Airport    = '星辰'
        Type       = $n.Type
        Server     = $n.Server
        ServerPort = $n.Port
        OrigName   = $n.OrigName
    })
    $xcPort++
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
      interval: 180
      tolerance: 50
      proxies:
$($groupLines -join "`r`n")
    - name: ALL
      type: select
      proxies:
$($groupLines -join "`r`n")
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
    Set-Content -LiteralPath (Join-Path $cd 'config.yaml') -Value $header -Encoding UTF8
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
    [IO.File]::WriteAllText((Join-Path $bd 'bridge.json'), $bridgeJsonText, (New-Object System.Text.UTF8Encoding($false)))
}

Write-Output "✅ AgentProxyHub 端口池与配置生成完成："
Write-Output "   - 蜂窝出口: $($fwNodes.Count) 个 (端口 $StartPort - $($StartPort + $fwNodes.Count - 1))"
Write-Output "   - 星辰出口: $($xcNodes.Count) 个 (端口 $XingchenStartPort - $($XingchenStartPort + $xcNodes.Count - 1))"
Write-Output "   - 总计出口: $($mapping.Count) 个"
Write-Output "   - 控制器  : 127.0.0.1:$ControllerPort"
Write-Output "   - 配置文件: $(Join-Path $OutDir 'config\config.yaml')"
