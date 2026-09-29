<#
.SYNOPSIS
    AgentProxyHub & 蜂窝/星辰节点池智能健康巡检与风控守护引擎 (Pool-Guard)
.DESCRIPTION
    1. 账号强粘性保护：已有 Google 账号绑定的节点非确凿物理故障或送中绝不切换，杜绝 IP 漂移封号。
    2. 全网动态呼吸充盈：全量并发巡检 125 个端口，自动发现复活节点并充入备用池，池子永不枯竭。
    3. 三级风控拦截：强力探测并剔除 Google 送中节点 (China/HK/MO) 与受限节点 (Cloudflare/Google 不通)。
    4. 自动守护熔断自愈：AutoGuard 模式下若检测到绑定节点送中或宕机，自动同区最小漂移平滑换绑纯净节点并安全重载网关。
    5. 严格遵守 gui_config.json 无 BOM、LF 编辑铁律。
.PARAMETER Mode
    Inspect: 只读体检模式 (默认)
    RefreshStandby: 充盈备选池 (绝对不动已有绑定)
    AutoGuard: 自动守护与熔断修复 (供定时计划任务或后台调用)
#>

param(
    [ValidateSet('Inspect', 'RefreshStandby', 'AutoGuard')]
    [string]$Mode = 'Inspect',
    [switch]$RestartGatewayIfChanged
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ScriptDir) { $ScriptDir = "D:\Program Files\AgentProxyHub" }

$ConfigPath = "C:\Users\1\.antigravity_tools\gui_config.json"
$NodesJsonPath = Join-Path $ScriptDir "nodes.json"
if (-not (Test-Path $NodesJsonPath)) {
    $NodesJsonPath = Join-Path $ScriptDir "data\nodes.json"
}
if (-not (Test-Path $NodesJsonPath)) {
    $NodesJsonPath = "D:\Program Files\FengWoBridge\nodes.json"
}

$AiTxtPath = Join-Path $ScriptDir "反重力-Gemini可用-socks5.txt"
$AuditLogPath = Join-Path $ScriptDir "logs\pool-guard-audit.log"
if (-not (Test-Path (Split-Path $AuditLogPath))) {
    New-Item -ItemType Directory -Path (Split-Path $AuditLogPath) -Force | Out-Null
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   AgentProxyHub 节点池智能风控守护引擎 (Auto-Guard)" -ForegroundColor Cyan
Write-Host "   运行模式: $Mode  |  时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. 读取基础配置
if (-not (Test-Path $ConfigPath)) { throw "未找到网关配置文件: $ConfigPath" }
if (-not (Test-Path $NodesJsonPath)) { throw "未找到节点元数据库: $NodesJsonPath" }

$cfg = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$nodesData = Get-Content $NodesJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
$accsData = Get-Content "C:\Users\1\.antigravity_tools\accounts.json" -Raw -Encoding UTF8 | ConvertFrom-Json

# Google Gemini 官方支持地区白名单 (严禁中国大陆、香港、澳门进入 AI 代理池)
$AiSupportedCountries = @(
    'United States', 'Japan', 'United Kingdom', 'Canada', 'Germany',
    'France', 'Taiwan', 'Singapore', 'Australia', 'Spain', 'Mexico',
    'Italy', 'Switzerland', 'Netherlands', 'Sweden', 'Poland'
)
$boundProps = $cfg.proxy.proxy_pool.account_bindings.PSObject.Properties
$boundMap = @{} # AccountId -> ProxyId
$boundPorts = @{} # AccountId -> Port
foreach ($bp in $boundProps) {
    $boundMap[$bp.Name] = $bp.Value
    $px = $cfg.proxy.proxy_pool.proxies | Where-Object { $_.id -eq $bp.Value }
    if ($px.url -match ':(\d+)') {
        $boundPorts[$bp.Name] = [int]$matches[1]
    }
}

Write-Host "`n[阶段 1] 正在检查当前账号绑定节点的【粘性锁定与防送中状态】..." -ForegroundColor Yellow
$boundHealth = @()
foreach ($bp in $boundProps) {
    $accId = $bp.Name
    $targetProxyId = $bp.Value
    $port = $boundPorts[$accId]
    $px = $cfg.proxy.proxy_pool.proxies | Where-Object { $_.id -eq $targetProxyId }
    $acc = $accsData.accounts | Where-Object { $_.id -eq $accId }
    $email = if ($acc) { $acc.email } else { $accId }
    
    # 防抖机制：连续探测两次，避免单次网络抖动误判
    $okCount = 0
    $latencies = @()
    $ggCountry = 'Unknown'
    
    for ($try = 1; $try -le 2; $try++) {
        $cf = curl.exe -s -o NUL -x socks5h://127.0.0.1:$port --max-time 3 -w "%{http_code}" "https://cp.cloudflare.com/generate_204" 2>&1
        $gg = curl.exe -s -o NUL -x socks5h://127.0.0.1:$port --max-time 3 -w "%{http_code}|%{time_starttransfer}" "https://daily-cloudcode-pa.googleapis.com/" 2>&1
        $parts = $gg -split '\|'
        if ($cf -eq '204' -and ($parts[0] -eq '404' -or $parts[0] -eq '200')) {
            $okCount++
            if ([double]$parts[1] -gt 0) { $latencies += [math]::Round([double]$parts[1] * 1000) }
        }
        if ($okCount -eq 0 -and $try -eq 1) { Start-Sleep -Milliseconds 300 }
    }
    
    # 核心风控：实测 Google 官方条款端点判定的归属国家（防送中）
    $rawTerms = & curl.exe -s --max-time 5 --ssl-no-revoke -x socks5h://127.0.0.1:$port https://policies.google.com/terms 2>$null
    $termsStr = ($rawTerms -join "`n")
    if ($termsStr -match 'Country version:</a>\s*([^<]+)') {
        $ggCountry = $matches[1].Trim()
    }
    
    $isSentToChina = ($ggCountry -in @('China', 'Hong Kong', 'Macao'))
    $isNetOk = ($okCount -gt 0)
    $isAlive = ($isNetOk -and -not $isSentToChina)
    $avgLat = if ($latencies.Count -gt 0) { [math]::Round(($latencies | Measure-Object -Average).Average) } else { 9999 }
    
    $statusText = if ($isAlive) {
        "HEALTHY (正常: $ggCountry)"
    } elseif ($isSentToChina) {
        "CRITICAL_SENT_TO_CHINA (Google送中: $ggCountry)"
    } else {
        "CRITICAL_DEAD (网络不通)"
    }
    
    $boundHealth += [PSCustomObject]@{
        AccountId = $accId
        Email = $email
        ProxyId = $targetProxyId
        Port = $port
        ProxyName = $px.name
        IsAlive = $isAlive
        IsSentToChina = $isSentToChina
        GoogleCountry = $ggCountry
        LatencyMs = $avgLat
        Status = $statusText
    }
}

$boundHealth | Select-Object Email, Port, GoogleCountry, LatencyMs, Status | Format-Table -AutoSize
$deadBound = @($boundHealth | Where-Object { -not $_.IsAlive })

if ($deadBound.Count -eq 0) {
    Write-Host "✅ 所有账号绑定节点全部存活且未送中！触发【强粘性锚定锁】，任何已绑 IP 保持原状，严禁漂移！" -ForegroundColor Green
} else {
    Write-Warning "⚠️ 检测到有 $($deadBound.Count) 个账号绑定的节点异常（送中或宕机）！"
}

# 2. 全量 125 端口高并发体检扫描 (呼吸充盈池)
Write-Host "`n[阶段 2] 正在高并发扫描全网 125 个端口 (发现复活节点与充盈备选池)..." -ForegroundColor Yellow

$allPorts = @(21001..21080) + @(22001..22045)
$pool = [RunspaceFactory]::CreateRunspacePool(1, 30)
$pool.Open()
$tasks = @()

foreach ($p in $allPorts) {
    $ps = [PowerShell]::Create()
    $ps.RunspacePool = $pool
    $null = $ps.AddScript({
        param($port)
        $cf = curl.exe -s -o NUL -x socks5h://127.0.0.1:$port --max-time 3 -w "%{http_code}" "https://cp.cloudflare.com/generate_204" 2>&1
        $gg = curl.exe -s -o NUL -x socks5h://127.0.0.1:$port --max-time 3 -w "%{http_code}|%{time_starttransfer}" "https://daily-cloudcode-pa.googleapis.com/" 2>&1
        $parts = $gg -split '\|'
        
        $cfOk = ($cf -eq '204')
        $ggOk = ($parts[0] -eq '404' -or $parts[0] -eq '200')
        $lat = if ([double]$parts[1] -gt 0) { [math]::Round([double]$parts[1] * 1000) } else { 9999 }
        
        [PSCustomObject]@{
            Port = $port
            Alive = ($cfOk -and $ggOk)
            Latency = $lat
        }
    }).AddArgument($p)
    $tasks += [PSCustomObject]@{ PS = $ps; Async = $ps.BeginInvoke() }
}

$sweepResults = @{}
foreach ($t in $tasks) {
    try {
        $res = $t.PS.EndInvoke($t.Async)
        $sweepResults[$res.Port] = $res
        $t.PS.Dispose()
    } catch { }
}
$pool.Close()
$pool.Dispose()

# 结合 nodesData 元数据进行三级风控过滤
$candidateList = @()
foreach ($item in $nodesData.nodes) {
    $p = [int]$item.port
    $probe = $sweepResults[$p]
    if ($probe -and $probe.Alive) {
        # 风控过滤：必须未送中！
        if (($item.googleCountry -in $AiSupportedCountries -or $item.country -in $AiSupportedCountries) -and -not $item.isSentToChina -and $item.googleCountry -notin @('China', 'Hong Kong', 'Macao')) {
            $candidateList += [PSCustomObject]@{
                Port = $p
                OrigName = $item.orig
                Country = $item.country
                GoogleCountry = $item.googleCountry
                Kind = $item.kind
                Latency = $probe.Latency
                IsBound = ($boundPorts.Values -contains $p)
            }
        }
    }
}

$sortedCandidates = @($candidateList | Sort-Object Latency)
Write-Host "✅ 全网扫描完成: 共发现 $($sortedCandidates.Count) 个【双通 + 未送中】的纯净健康节点！" -ForegroundColor Green

if ($Mode -eq 'Inspect') {
    Write-Host "`n=== 纯净推荐节点 TOP 15 (延迟最优，自动过滤送中) ===`n" -ForegroundColor Cyan
    $sortedCandidates | Select-Object -First 15 | Format-Table -AutoSize
    Write-Host "Inspect 体检模式结束，未对系统做任何变更。" -ForegroundColor Gray
    return
}

# 3. 如果是 RefreshStandby 或 AutoGuard，执行配置安全回写
Write-Host "`n[阶段 3] 正在同步与充盈 Antigravity 代理池及导出清单..." -ForegroundColor Yellow

$needRestart = $false
$auditLogs = @()

# 检查是否需要替补异常绑定 (包括宕机与送中)
if ($Mode -eq 'AutoGuard' -and $deadBound.Count -gt 0) {
    foreach ($db in $deadBound) {
        $deadMeta = $nodesData.nodes | Where-Object { $_.port -eq $db.Port }
        $targetCountry = if ($deadMeta) { $deadMeta.country } else { 'Unknown' }
        
        # 寻找同国/同区最快未绑定且未送中的替补
        $sub = $null
        foreach ($cand in ($sortedCandidates | Where-Object { -not $_.IsBound })) {
            if ($cand.Country -eq $targetCountry -or $cand.GoogleCountry -eq $deadMeta.googleCountry) {
                # 双重校验：实地测试替补节点的 Google 归属国
                $tCheck = & curl.exe -s --max-time 4 --ssl-no-revoke -x socks5h://127.0.0.1:$($cand.Port) https://policies.google.com/terms 2>$null
                $tStr = ($tCheck -join "`n")
                $tGg = 'Unknown'
                if ($tStr -match 'Country version:</a>\s*([^<]+)') { $tGg = $matches[1].Trim() }
                if ($tGg -notin @('China', 'Hong Kong', 'Macao', 'Unknown')) {
                    $sub = $cand
                    break
                }
            }
        }
        
        if (-not $sub) {
            # 无同国节点时选全局最快未绑定的纯净节点
            foreach ($cand in ($sortedCandidates | Where-Object { -not $_.IsBound })) {
                $tCheck = & curl.exe -s --max-time 4 --ssl-no-revoke -x socks5h://127.0.0.1:$($cand.Port) https://policies.google.com/terms 2>$null
                $tStr = ($tCheck -join "`n")
                $tGg = 'Unknown'
                if ($tStr -match 'Country version:</a>\s*([^<]+)') { $tGg = $matches[1].Trim() }
                if ($tGg -notin @('China', 'Hong Kong', 'Macao', 'Unknown')) {
                    $sub = $cand
                    break
                }
            }
        }
        
        if ($sub) {
            $subPort = $sub.Port
            $sub.IsBound = $true
            $boundPorts[$db.AccountId] = $subPort
            $reason = if ($db.IsSentToChina) { '已被Google送中(400锁区)' } else { '物理连接故障' }
            $msg = "⚡ 账号 $($db.Email) 绑定的节点 $($db.Port) $reason，同区最小漂移自动切换到纯净节点: $($subPort) ($($sub.OrigName) - $($sub.Country))"
            Write-Warning $msg
            $auditLogs += "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
            
            # 在 proxies 中找到并替换该代理的 URL 与名称
            $targetProxy = $cfg.proxy.proxy_pool.proxies | Where-Object { $_.id -eq $db.ProxyId }
            if ($targetProxy) {
                $brand = if ($subPort -lt 22000) { '蜂窝' } else { '星辰' }
                $targetProxy.url = "socks5h://127.0.0.1:$subPort"
                $targetProxy.name = "$brand-$($sub.OrigName)$subPort"
                $targetProxy.is_healthy = $true
                $targetProxy.latency = $sub.Latency
            }
            $needRestart = $true
        }
    }
}

# 充盈备选池（挑选 Top 25 优质存活未送中节点进池）
$finalPorts = @()
# 先把所有当前绑定的端口放进去
foreach ($bp in $boundPorts.Values) { $finalPorts += $bp }
# 再把延迟最优的备用节点填充进去，凑够 25 个
foreach ($cand in $sortedCandidates) {
    if ($finalPorts.Count -ge 25) { break }
    if ($finalPorts -notcontains $cand.Port) {
        $finalPorts += $cand.Port
    }
}

# 重构 cleanProxies 列表，严格维持已有 ID 不变
$newProxies = @()
foreach ($p in $finalPorts) {
    $exist = $cfg.proxy.proxy_pool.proxies | Where-Object { $_.url -match ":$p\b" } | Select-Object -First 1
    $meta = $nodesData.nodes | Where-Object { $_.port -eq $p }
    $brand = if ($p -lt 22000) { '蜂窝' } else { '星辰' }
    
    $targetProxyId = if ($exist) { $exist.id } else { [guid]::NewGuid().ToString() }
    $pName = if ($exist -and $exist.name -notmatch '^Proxy \d+$') { $exist.name } else { "$brand-$($meta.orig)$p" }
    
    $isAccountBound = ($boundPorts.Values -contains $p)
    $newProxies += [pscustomobject]@{
        id = $targetProxyId
        name = $pName
        url = "socks5h://127.0.0.1:$p"
        auth = $null
        enabled = $true
        priority = if ($isAccountBound) { 0 } else { 1 }
        tags = @("gemini-pure")
        max_accounts = $null
        health_check_url = $null
        last_check_time = 1790581174
        is_healthy = $true
        latency = if ($exist.latency) { $exist.latency } else { 500 }
    }
}

$cfg.proxy.proxy_pool.proxies = $newProxies

# 安全写入 gui_config.json (铁律: 无 BOM, LF)
$bakFile = "$ConfigPath.bak-guard-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item $ConfigPath $bakFile
$jsonText = ($cfg | ConvertTo-Json -Depth 20) -replace "`r`n", "`n"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($ConfigPath, $jsonText, $utf8NoBom)

# 校验自检
$bytes = [System.IO.File]::ReadAllBytes($ConfigPath)
if ($bytes[0] -ne 123) { throw "写入安全异常：首字节不是 123，疑似混入 BOM！已中止！" }
$testJson = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($testJson.proxy.proxy_pool.proxies.Count -ne $newProxies.Count) { throw "写入校验失败：节点数量异常！" }

Write-Host "✅ gui_config.json 写入自检通过: 代理池已充盈至 $($newProxies.Count) 个高质量双通纯净节点！" -ForegroundColor Green

# 同步对齐反重力纯净导出清单
$pureLines = foreach ($item in ($sortedCandidates | Select-Object -First 30)) {
    "socks5://127.0.0.1:$($item.Port)"
}
[System.IO.File]::WriteAllText($AiTxtPath, ($pureLines -join "`r`n"), [System.Text.Encoding]::UTF8)
Write-Host "✅ 反重力-Gemini可用-socks5.txt 纯净清单已同步更新！" -ForegroundColor Green

# 记录审计日志
if ($auditLogs.Count -gt 0) {
    Add-Content -Path $AuditLogPath -Value ($auditLogs -join "`r`n") -Encoding UTF8
}

# 如有变动或要求重启网关
if ($RestartGatewayIfChanged -and $needRestart) {
    Write-Host "正在平滑重载 Antigravity Tools 网关进程..." -ForegroundColor Cyan
    $procs = Get-Process -Name "antigravity-tools" -ErrorAction SilentlyContinue
    if ($procs) {
        foreach ($pr in $procs) {
            try { taskkill /PID $pr.Id /T /F | Out-Null } catch {}
        }
        Start-Sleep -Seconds 2
    }
    Start-Process -FilePath "D:\Program Files\Antigravity Tools\antigravity-tools.exe" -WorkingDirectory "D:\Program Files\Antigravity Tools"
    Start-Sleep -Seconds 3
    Write-Host "网关重载完成！" -ForegroundColor Green
}

Write-Host "`n守护巡检与池子充盈全部完成！" -ForegroundColor Cyan
