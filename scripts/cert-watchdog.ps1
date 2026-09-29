# ==============================================================================
# AgentProxyHub · 证书漂移看门狗
# ==============================================================================
# 背景：2026-09-29 实证机场网关证书整体轮换（统一迁 gateway.zryc.tech），蜂窝桥
#       三个节点因 SNI 校验失败集体"假死"，而面板评级还是 S——无人发现半天。
# 作用：定时探测全部 socks 出口；仅对"上游 TLS 证书校验失败"类死口自动补
#       skip-cert-verify 并热重载 mihomo；其余故障只记录不动作（防误伤）。
# 频率：计划任务 AgentProxyHub-CertWatchdog（每小时）
# 日志：D:\Program Files\FengWoBridge\logs\cert-watchdog.log
# 卸载：schtasks /Delete /TN AgentProxyHub-CertWatchdog /F
# ==============================================================================

$ErrorActionPreference = 'Continue'
$fwDir     = 'D:\Program Files\FengWoBridge'
$configPath = Join-Path $fwDir 'config.yaml'
$logPath    = Join-Path $fwDir 'logs\cert-watchdog.log'
$bridgeLog  = Join-Path $fwDir 'logs\bridge.log'

function Log([string]$msg) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

if (-not (Test-Path -LiteralPath $configPath)) { Log '[ERROR] 找不到 config.yaml'; exit 1 }
$config = Get-Content -LiteralPath $configPath -Encoding UTF8

# 1. 解析 listener 端口 -> 代理名（in-21050 -> fw-21050）
$map = [ordered]@{}
$cur = $null
foreach ($line in $config) {
    if ($line -match '-\s*name:\s*in-(\d+)') { $cur = $Matches[1]; continue }
    if ($cur -and $line -match '^\s*proxy:\s*(\S+)') { $map[$cur] = $Matches[1]; $cur = $null }
}
if ($map.Count -eq 0) { Log '[ERROR] 未解析到任何 listener'; exit 1 }

# 2. 逐口实测出口（curl.exe 系统自带；探不通记死口）
$dead = @()
foreach ($port in $map.Keys) {
    $ip = & curl.exe -s --max-time 10 --socks5-hostname "127.0.0.1:$port" https://api.ipify.org 2>$null
    if (-not $ip) { $dead += [string]$port }
}

# 3. bridge.log 尾部判定死因：仅"failed to verify certificate"归为证书漂移类
$logTail = ''
if (Test-Path -LiteralPath $bridgeLog) {
    $logTail = (Get-Content -LiteralPath $bridgeLog -Tail 400 -ErrorAction SilentlyContinue) -join "`n"
}

$healPorts = @()
foreach ($port in $dead) {
    $proxy = $map[$port]
    if (-not $proxy) { continue }
    $isCert = $logTail -match ('dial\s+' + [regex]::Escape($proxy) + '\s.*failed to verify certificate')
    $line = $config | Where-Object { $_ -match ('name:\s*' + [regex]::Escape($proxy) + '\b') } | Select-Object -First 1
    if (-not $line) { continue }
    if ($isCert -and $line -notmatch 'skip-cert-verify') {
        $healPorts += [pscustomobject]@{ Port = $port; Proxy = $proxy }
    } elseif (-not $isCert) {
        Log "[WARN] 端口 $port ($proxy) 不通但非证书类故障，仅记录不动作"
    }
}

# 4. 只在确需 healing 时改配置（平时零动作、零闪断）
if ($healPorts.Count -gt 0) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Copy-Item -LiteralPath $configPath -LiteralPath "$configPath.bak-watchdog-$stamp" -Force
    $healNames = $healPorts | ForEach-Object { $_.Proxy }
    $newLines = New-Object System.Collections.Generic.List[string]
    foreach ($line in $config) {
        $hit = $false
        foreach ($name in $healNames) {
            if ($line -match ('name:\s*' + [regex]::Escape($name) + '\b') -and $line -notmatch 'skip-cert-verify') { $hit = $true; break }
        }
        if ($hit) { $newLines.Add((($line -replace '\}\s*$', ', skip-cert-verify: true }')).TrimEnd()) }
        else { $newLines.Add($line) }
    }
    Set-Content -LiteralPath $configPath -Value $newLines -Encoding UTF8

    # 从 config.yaml 现读控制器地址与密钥，不硬编码
    $ctrl = $null; $secret = ''
    foreach ($line in $config) {
        if (-not $ctrl -and $line -match 'external-controller:\s*(\S+)') { $ctrl = $Matches[1] }
        if ($line -match '^secret:\s*"?([^"\s]+)') { $secret = $Matches[1] }
    }
    if (-not $ctrl) { Log '[ERROR] 补丁已写入但找不到 external-controller，请手动重载 mihomo'; exit 1 }
    try {
        Invoke-RestMethod -Method Put -Uri "http://$ctrl/configs?force=true" `
            -Headers @{ Authorization = "Bearer $secret" } `
            -ContentType 'application/json' -Body '{"path":"","payload":""}' | Out-Null
        Log ("[HEAL] 修复 {0} 个节点（{1}）并热重载 mihomo，配置备份 {2}" -f `
            $healPorts.Count, (($healPorts | ForEach-Object { "$($_.Port)->$($_.Proxy)" }) -join ', '), "$configPath.bak-watchdog-$stamp")
    } catch {
        Log "[ERROR] 补丁已写入但热重载失败：$_（可手动重载或重启 mihomo）"
    }
} elseif ($dead.Count -gt 0) {
    Log "[INFO] 探测完成：死口 $($dead -join ',')，无需 healing"
} else {
    Log "[INFO] 探测完成：全部 $($map.Count) 口存活"
}
