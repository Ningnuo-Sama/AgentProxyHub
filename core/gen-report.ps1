# ==============================================================================
# AgentProxyHub 多场景智能测绘探针引擎 (Multi-Scene Probe & Benchmark Engine)
# ==============================================================================
# 功能：并发实测每个本地 SOCKS5 端口的出口 IP、地理归属、住宅/机房属性、送中检测及
#       多场景靶场 (Gemini/Google, Claude, OpenAI, Facebook) 的连通状态与综合评分
# 数据输出：data/nodes.json（供桌面面板与 MCP Server 消费）

param(
    [string]$RootDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$Listen = "127.0.0.1",
    [string]$ScenesConfig = "",
    [switch]$SkipProbe
)

$ErrorActionPreference = 'Stop'

function Invoke-Curl([string[]]$CurlArgs) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { return (& curl.exe @CurlArgs 2>$null | Out-String) }
    finally { $ErrorActionPreference = $prev }
}

$dataDir = Join-Path $RootDir 'data'
if (-not (Test-Path -LiteralPath $dataDir)) { [void](New-Item -ItemType Directory -Path $dataDir -Force) }

$csvPath = Join-Path $dataDir 'port_map.csv'
if (-not (Test-Path -LiteralPath $csvPath)) {
    # 尝试从运行目录或根目录搜寻 port_map.csv 或 端口对照.csv
    $altCsv = Join-Path $RootDir '端口对照.csv'
    if (Test-Path -LiteralPath $altCsv) {
        $csvPath = $altCsv
    } else {
        $sysCsv = "D:\Program Files\FengWoBridge\端口对照.csv"
        if (Test-Path -LiteralPath $sysCsv) { $csvPath = $sysCsv }
    }
}

if (-not (Test-Path -LiteralPath $csvPath)) {
    throw "缺少端口映射文件 ($csvPath)，请先运行配置生成器。"
}

$map = Import-Csv -LiteralPath $csvPath
$ipCache = Join-Path $env:TEMP 'agentproxyhub_exitip.tsv'
$googleCache = Join-Path $env:TEMP 'agentproxyhub_google.tsv'
$claudeCache = Join-Path $env:TEMP 'agentproxyhub_claude.tsv'
$openaiCache = Join-Path $env:TEMP 'agentproxyhub_openai.tsv'

# 读取 scenes.json 规则
if (-not $ScenesConfig) { $ScenesConfig = Join-Path $RootDir 'config\scenes.json' }
$scenesRules = @()
if (Test-Path -LiteralPath $ScenesConfig) {
    try { $scenesRules = Get-Content -LiteralPath $ScenesConfig -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
}

# ---------- 1. 逐端口实测出口 IP ----------
$exitIp = @{}
if ($SkipProbe -and (Test-Path -LiteralPath $ipCache)) {
    foreach ($l in (Get-Content -LiteralPath $ipCache -Encoding UTF8)) {
        $kv = $l -split "`t"
        if ($kv.Count -ge 2) { $exitIp[$kv[0]] = $kv[1] }
    }
} else {
    Write-Output "正在探测 $($map.Count) 个端口的真实出口 IP..."
    foreach ($row in $map) {
        $p = $row.ListenPort
        $ip = ''
        for ($try = 1; $try -le 2; $try++) {
            $ip = (Invoke-Curl @('-s', '--ssl-no-revoke', '--max-time', '10', '--connect-timeout', '6',
                    '--socks5-hostname', "$Listen`:$p", 'http://api.ipify.org')).Trim()
            if ($ip -match '^[0-9]{1,3}(\.[0-9]{1,3}){3}$') { break }
            Start-Sleep -Milliseconds 150
        }
        if ($ip -notmatch '^[0-9]{1,3}(\.[0-9]{1,3}){3}$') { $ip = 'FAIL' }
        $exitIp[$p] = $ip
    }
    ($exitIp.Keys | Sort-Object | ForEach-Object { "$_`t$($exitIp[$_])" }) |
        Set-Content -LiteralPath $ipCache -Encoding utf8
}

# ---------- 2. 归属地与网络类型查询（ip-api 批量） ----------
$uniqueIps = $exitIp.Values | Where-Object { $_ -ne 'FAIL' } | Sort-Object -Unique
$geo = @{}
if ($uniqueIps.Count -gt 0) {
    $body = ConvertTo-Json @($uniqueIps) -Compress
    $tmp = Join-Path $env:TEMP 'agentproxyhub_geo.json'
    [IO.File]::WriteAllText($tmp, $body, (New-Object System.Text.UTF8Encoding($false)))
    $fields = 'status,message,country,countryCode,city,isp,org,as,mobile,proxy,hosting,query'
    for ($try = 1; $try -le 2; $try++) {
        $resp = Invoke-Curl @('-s', '--ssl-no-revoke', '--max-time', '30',
            '-H', 'Content-Type: application/json', '--data-binary', "@$tmp",
            "http://ip-api.com/batch?fields=$fields")
        try {
            $parsed = $resp | ConvertFrom-Json
            foreach ($g in $parsed) { if ($g.status -eq 'success') { $geo[$g.query] = $g } }
            if ($geo.Count -gt 0) { break }
        } catch { Start-Sleep -Seconds 1 }
    }
}

function Get-Kind($g) {
    if (-not $g) { return '未知' }
    if ($g.hosting) { return '机房' }
    if ($g.mobile) { return '移动网络' }
    return '住宅/家宽'
}

# ---------- 3. 并发实测多场景靶场 (Google / Claude / OpenAI) ----------
$alivePorts = @($map | Where-Object { $exitIp[$_.ListenPort] -ne 'FAIL' } | ForEach-Object { [int]$_.ListenPort })

$googleRegion = @{}
$claudeStatus = @{}
$openaiStatus = @{}

Write-Output "正在并发实测 Google送中、Claude直连、OpenAI可用性..."
$pool = [RunspaceFactory]::CreateRunspacePool(1, 24)
$pool.Open()
$tasks = @()

foreach ($p in $alivePorts) {
    $ps = [PowerShell]::Create()
    $ps.RunspacePool = $pool
    $null = $ps.AddScript({
        param($port, $listen)
        $sock = "$listen`:$port"
        
        # 1. Google 官方认定国家
        $gCountry = 'FAIL'
        $gOut = & curl.exe -s --max-time 5 --ssl-no-revoke --socks5-hostname $sock "https://policies.google.com/terms" 2>$null | Out-String
        if ($gOut -match 'Country version:</a> ([^<]*)') {
            $gCountry = $Matches[1].Trim()
        } elseif ($gOut -match 'policies\.google\.com') {
            $gCountry = 'Unknown'
        }

        # 2. Claude (Anthropic) 连通性测试
        $claudeOk = $false
        $cOut = & curl.exe -s --max-time 6 --ssl-no-revoke -I --socks5-hostname $sock "https://api.anthropic.com" 2>$null | Out-String
        if ($cOut -match 'HTTP/(1\.1|2)\s+([2345]\d\d)') {
            $code = [int]$Matches[2]
            # 只要不是 403 阻断或 Cloudflare error，401/404/200 都说明路由未被封锁
            if ($code -ne 403 -and $code -lt 500) { $claudeOk = $true }
            if ($cOut -match 'cloudflare' -and $code -eq 403) { $claudeOk = $false }
        }

        # 3. OpenAI 连通性测试
        $openaiOk = $false
        $oOut = & curl.exe -s --max-time 6 --ssl-no-revoke -I --socks5-hostname $sock "https://api.openai.com/v1/models" 2>$null | Out-String
        if ($oOut -match 'HTTP/(1\.1|2)\s+([2345]\d\d)') {
            $code = [int]$Matches[2]
            # 401 意味着未授权但 API 畅通无阻，非 403 被阻断
            if ($code -eq 401 -or $code -eq 200) { $openaiOk = $true }
        }

        return [pscustomobject]@{
            Port = $port
            GoogleCountry = $gCountry
            ClaudeOk = $claudeOk
            OpenAiOk = $openaiOk
        }
    }).AddArgument($p).AddArgument($Listen)

    $tasks += [pscustomobject]@{ PS = $ps; Async = $ps.BeginInvoke() }
}

foreach ($t in $tasks) {
    try {
        $res = $t.PS.EndInvoke($t.Async)
        if ($res) {
            $googleRegion["$($res.Port)"] = $res.GoogleCountry
            $claudeStatus["$($res.Port)"] = [bool]$res.ClaudeOk
            $openaiStatus["$($res.Port)"] = [bool]$res.OpenAiOk
        }
    } catch { }
    finally { $t.PS.Dispose() }
}
$pool.Dispose()

# ---------- 4. 重复 IP 冲突分析 ----------
$ipGroups = $map | ForEach-Object { [pscustomobject]@{ Port = $_.ListenPort; Ip = $exitIp[$_.ListenPort] } } |
    Where-Object { $_.Ip -ne 'FAIL' } | Group-Object Ip
$dupIps = $ipGroups | Where-Object { $_.Count -gt 1 }
$dupPortSet = @{}
foreach ($d in $dupIps) { foreach ($item in $d.Group) { $dupPortSet["$($item.Port)"] = $true } }

# ---------- 5. 核心判定与场景匹配打分 ----------
$AiSupportedCountries = @(
    'United States', 'Japan', 'United Kingdom', 'Canada', 'Germany',
    'France', 'Taiwan', 'Singapore', 'Australia', 'Spain', 'Mexico',
    'Italy', 'Switzerland', 'Netherlands', 'Sweden', 'Poland'
)

$jsonNodes = foreach ($row in $map) {
    $p = [int]$row.ListenPort
    $ip = $exitIp["$p"]
    $isFail = ($ip -eq 'FAIL' -or [string]::IsNullOrWhiteSpace($ip))
    $g = if (-not $isFail) { $geo[$ip] } else { $null }
    $gCountry = if ($googleRegion.ContainsKey("$p")) { $googleRegion["$p"] } else { 'FAIL' }
    $isDup = $dupPortSet.ContainsKey("$p")
    $kind = if (-not $isFail) { Get-Kind $g } else { '未知' }
    $physCountry = if ($g) { $g.country } else { '未知' }

    # 送中判定
    $isSentToChina = ($gCountry -eq 'China' -and $physCountry -notin @('China', 'Hong Kong', '未知'))
    $isHkOrCn = ($gCountry -eq 'China' -or $gCountry -eq 'Hong Kong' -or $physCountry -in @('China', 'Hong Kong'))

    # 各场景支持判定
    $antigravityOk = (-not $isFail -and -not $isHkOrCn -and -not $isSentToChina -and ($gCountry -in $AiSupportedCountries))
    $claudeOk = (-not $isFail -and -not $isHkOrCn -and -not $isSentToChina -and ($claudeStatus["$p"] -eq $true))
    $openaiOk = (-not $isFail -and -not $isHkOrCn -and ($openaiStatus["$p"] -eq $true))
    $facebookOk = (-not $isFail -and -not $isHkOrCn -and -not $isSentToChina -and ($kind -eq '住宅/家宽' -or $kind -eq '移动网络') -and -not $isDup)
    $generalOk = (-not $isFail)

    # 综合健康度打分 (0-100)
    $score = 0
    $rating = 'F'
    if (-not $isFail) {
        if ($isHkOrCn) {
            $score = 0; $rating = 'F'
        } else {
            $score = 75
            if ($antigravityOk) { $score += 10 }
            if ($claudeOk) { $score += 5 }
            if ($openaiOk) { $score += 5 }
            if ($kind -eq '住宅/家宽') { $score += 5 }
            if ($isDup) { $score -= 10 }
            if ($row.OrigName -match '专线|原生') { $score += 5 }
            if ($score -gt 100) { $score = 100 }
            if ($score -lt 0) { $score = 0 }

            $rating = if ($score -ge 90) { 'S' } elseif ($score -ge 80) { 'A' } elseif ($score -ge 70) { 'B' } else { 'C' }
        }
    }

    [pscustomobject]@{
        port                 = $p
        httpPort             = if ($row.HttpPort) { [int]$row.HttpPort } else { ($p + 10000) }
        name                 = if ($row.ProxyName) { $row.ProxyName } else { "node-$p" }
        orig                 = if ($row.OrigName) { $row.OrigName } else { "node-$p" }
        type                 = if ($row.Type) { $row.Type } else { "socks5" }
        upstream             = if ($row.Server) { "$($row.Server):$($row.ServerPort)" } else { "upstream" }
        ip                   = if ($isFail) { $null } else { $ip }
        country              = if ($g) { $g.country } else { $null }
        countryCode          = if ($g) { $g.countryCode } else { $null }
        city                 = if ($g) { $g.city } else { $null }
        isp                  = if ($g) { $g.isp } else { $null }
        asn                  = if ($g) { ($g.as -split ' ')[0] } else { $null }
        kind                 = $kind
        googleCountry        = $gCountry
        isSentToChina        = $isSentToChina
        isDuplicateIp        = $isDup
        healthScore          = $score
        healthRating         = $rating
        antigravitySupported = $antigravityOk
        claudeSupported      = $claudeOk
        openaiSupported      = $openaiOk
        facebookSupported    = $facebookOk
        generalSupported     = $generalOk
        scenes               = [pscustomobject]@{
            antigravity = $antigravityOk
            claude      = $claudeOk
            openai      = $openaiOk
            facebook    = $facebookOk
            general     = $generalOk
        }
        boundProfile         = $null
    }
}

$report = [pscustomobject]@{
    generatedAt  = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    listen       = $Listen
    total        = $jsonNodes.Count
    alive        = ($jsonNodes | Where-Object { $_.ip -ne $null }).Count
    claudeReady  = ($jsonNodes | Where-Object { $_.claudeSupported }).Count
    openaiReady  = ($jsonNodes | Where-Object { $_.openaiSupported }).Count
    fbReady      = ($jsonNodes | Where-Object { $_.facebookSupported }).Count
    antigravityReady = ($jsonNodes | Where-Object { $_.antigravitySupported }).Count
    nodes        = $jsonNodes
}

$nodesJsonPath = Join-Path $dataDir 'nodes.json'
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $nodesJsonPath -Encoding utf8
Write-Output "✅ 测绘完成！总端口: $($report.total) | 在线: $($report.alive) | Claude达标: $($report.claudeReady) | OpenAI达标: $($report.openaiReady)"
