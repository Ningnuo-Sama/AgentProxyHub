# ============================================================================
# panel-ledger.ps1 — 端口级对齐账本（P2-21 / t44）
#   颗粒度 = **端口**；数据源 = 后端真实账本文件，**全部为动态活数据**（严禁静态样例）。
#   主数据源优先级：data\l0_state.json（后端每轮刷新的端口级账本）
#                 → data\port_map_lock.json（映射冻结锁表）
#                 → data\port_map.csv（生成器产物，仅补订阅源名）
#   本文件不依赖 WPF，可单独 dot-source 自验：
#       . .\ui\panel-ledger.ps1 ; Get-PortLedger | Format-Table
#   红线：只读账本；不打印凭据字段；不写 config.yaml。
# ============================================================================

if (-not $script:APH_Root) {
    if ($PSScriptRoot) { $script:APH_Root = Split-Path -Parent $PSScriptRoot } else { $script:APH_Root = 'D:\Program Files\AgentProxyHub' }
}
$script:APH_DataDir    = Join-Path $script:APH_Root 'data'
$script:APH_SwitchFile = Join-Path $script:APH_DataDir 'auto_rebuild_state.json'
$script:APH_FreshnessSec = 48 * 3600      # 探测新鲜度阈值：>48h ⇒ 不新鲜，UI 必须显式标灰
$script:APH_DensityCap   = 2              # 密度上限：**按账号、按出口**（用户裁定「一个 IP 最多 2 个号」）

function Read-AphJson {
    param([string]$Name, [string]$Dir)
    if (-not $Dir) { $Dir = $script:APH_DataDir }
    $p = Join-Path $Dir $Name
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    try { return (Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

function Get-AphFileStamp {
    param([string]$Name)
    $p = Join-Path $script:APH_DataDir $Name
    if (-not (Test-Path -LiteralPath $p)) { return '' }
    return (Get-Item -LiteralPath $p).LastWriteTime.ToString('MM-dd HH:mm')
}

# ============================================================== A. 自动重建开关
# 开关状态落在独立状态文件（可读/可审计/可写/一行回滚）；**默认关（fail-closed）**。
function Get-AutoRebuildSwitch {
    $j = Read-AphJson 'auto_rebuild_state.json'
    $val = $false
    $src = '默认 fail-closed（无状态文件 ⇒ 关）'
    if ($j -and ($j.PSObject.Properties.Name -contains 'auto_rebuild_enabled')) {
        $val = [bool]$j.auto_rebuild_enabled
        $src = "auto_rebuild_state.json @ $($j.updated_at)"
    }
    return [pscustomobject]@{
        Enabled = $val
        Text    = if ($val) { '开' } else { '关（映射冻结）' }
        Source  = $src
        File    = $script:APH_SwitchFile
    }
}

function Set-AutoRebuildSwitch {
    param([Parameter(Mandatory = $true)][bool]$Enabled, [string]$Note = '')
    $doc = [ordered]@{
        version              = 1
        auto_rebuild_enabled = $Enabled
        updated_at           = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        updated_by           = 'panel.ps1 / panel-ledger.ps1（P2-21 / t44）'
        note                 = if ($Note) { $Note } else { 'P-1 映射冻结的显式开关：关 = 蜂窝订阅刷新后**不再**触发 gen-config.ps1 自动重建与内核热重载；开 = 回到旧行为。' }
        rollback             = '把 auto_rebuild_enabled 改成 false，或直接删除本文件（缺失即默认关）—— 无需改代码。'
    }
    ($doc | ConvertTo-Json) | Set-Content -LiteralPath $script:APH_SwitchFile -Encoding UTF8
    return (Get-AutoRebuildSwitch)
}

function Test-AutoRebuildAllowed { return [bool](Get-AutoRebuildSwitch).Enabled }

# ============================================================== B. 端口级账本
function Get-PortLedger {
    param([int[]]$Ports)

    $l0    = Read-AphJson 'l0_state.json'            # ← 主数据源：后端端口级账本（每轮刷新）
    $lock  = Read-AphJson 'port_map_lock.json'       # ← 映射冻结锁表
    $bind  = Read-AphJson 'bindings.json'            # ← 在册绑定（契约）
    $guard = Read-AphJson 'account_guard_state.json' # ← 逐口巡检结论 + 谁在用这个口
    $conf  = Read-AphJson 'confidence_state.json'    # ← 逐口最新实测（ip / googleCountry / t）
    $nodes = Read-AphJson 'nodes.json'               # ← 兜底实测（更旧）
    $dead  = Read-AphJson 'dead_accounts.json'       # ← 死号/退用注册表
    $sw    = Get-AutoRebuildSwitch

    # ①+⑤ port → proxy 名：**以后端账本为唯一来源**（port ≠ proxy 名！）
    $proxyByPort = @{}; $srcByPort = @{}
    if ($l0 -and $l0.listener_proxy_map) {
        foreach ($p in $l0.listener_proxy_map.PSObject.Properties) { $proxyByPort[[int]$p.Name] = [string]$p.Value; $srcByPort[[int]$p.Name] = 'l0_state' }
    }
    if ($lock -and $lock.ports) {
        foreach ($p in $lock.ports.PSObject.Properties) {
            $k = [int]$p.Name
            if (-not $proxyByPort.ContainsKey($k)) { $proxyByPort[$k] = [string]$p.Value.name; $srcByPort[$k] = 'port_map_lock' }
        }
    }
    # 仅补「订阅源名 / 品牌」（生成器产物，可能落后于现网，故单独标源）
    $csvByPort = @{}
    $csvPath = Join-Path $script:APH_DataDir 'port_map.csv'
    if (Test-Path -LiteralPath $csvPath) { foreach ($r in (Import-Csv -LiteralPath $csvPath -Encoding UTF8)) { $csvByPort[[int]$r.ListenPort] = $r } }

    # ③ 密度：**按出口 IP 聚合**（后端账本 exit_density 以 proxy 名为键，一个 proxy 可服务多口）
    $densityByProxy = @{}
    if ($l0 -and $l0.exit_density) { foreach ($p in $l0.exit_density.PSObject.Properties) { $densityByProxy[[string]$p.Name] = [int]$p.Value } }

    # ② 逐口最新实测
    $confByPort = @{}
    if ($conf -and $conf.ports) { foreach ($p in $conf.ports.PSObject.Properties) { $confByPort[[int]$p.Name] = $p.Value } }
    $nodeByPort = @{}
    if ($nodes -and $nodes.nodes) { foreach ($n in $nodes.nodes) { $nodeByPort[[int]$n.port] = $n } }

    # ⑥ 谁在用这个口（Antigravity:<at账号> / 环境:<profile>）
    $whoByPort = @{}
    if ($guard -and $guard.ports) { foreach ($e in $guard.ports) { $whoByPort[[int]$e.port] = @($e.who) } }

    # AT 在册账号（accounts.json 仅邮箱/名称，无凭据）
    $atEmails = @()
    $accFile = Join-Path $env:USERPROFILE '.antigravity_tools\accounts.json'
    if (Test-Path -LiteralPath $accFile) {
        try { $acc = Get-Content -LiteralPath $accFile -Raw -Encoding UTF8 | ConvertFrom-Json; foreach ($a in $acc) { if ($a.email) { $atEmails += ([string]$a.email).ToLower() } } } catch { }
    }
    $deadNames = @{}
    if ($dead -and $dead.accounts) { foreach ($p in $dead.accounts.PSObject.Properties) { $deadNames[$p.Name.ToLower()] = $p.Value } }

    function Resolve-Identity([string]$tag) {
        if (-not $tag) { return [pscustomobject]@{ Kind = ''; Name = ''; Live = $false; Reason = '' } }
        $i = $tag.IndexOf(':')
        $kind = if ($i -gt 0) { $tag.Substring(0, $i) } else { '' }
        $name = if ($i -gt 0) { $tag.Substring($i + 1) } else { $tag }
        $live = $false; $reason = ''
        if ($kind -eq 'Antigravity') {
            $live = ($atEmails -contains $name.ToLower())
            if (-not $live) { $reason = 'AT 账号已不在册（accounts.json 无此邮箱）⇒ 陈旧绑定，不计入密度' }
        } else {
            $key = $name.ToLower()
            if ($deadNames.ContainsKey($key)) {
                $st = [string]$deadNames[$key].status
                $reason = "死号注册表 status=$st ⇒ fail-closed"
                $live = @('active', 'alive', 'healthy', 'in_use') -contains $st
            } else { $live = $true }
        }
        return [pscustomobject]@{ Kind = $kind; Name = $name; Live = $live; Reason = $reason }
    }

    $confStamp = if ($conf -and $conf.updatedAt) { [string]$conf.updatedAt } else { '' }
    $now = [DateTimeOffset]::UtcNow
    $rows = New-Object System.Collections.Generic.List[object]
    $all = if ($Ports -and $Ports.Count) { $Ports } else { @($proxyByPort.Keys | Sort-Object) }

    foreach ($port in $all) {
        $px = [string]$proxyByPort[$port]
        $cf = $confByPort[$port]
        $nd = $nodeByPort[$port]
        $pm = $csvByPort[$port]

        # ② 实测出口 IP + Google 判国 + ⑦ 探龄（一律取 lastProbe；绝不用池名/节点名/订阅名当判据）
        $exitIp = ''; $google = ''; $physical = ''; $srcTxt = ''; $ageH = $null; $probeT = ''
        if ($cf -and $cf.lastProbe -and $cf.lastProbe.ip) {
            $exitIp = [string]$cf.lastProbe.ip
            $google = [string]$cf.lastProbe.googleCountry
            $physical = [string]$cf.lastProbe.country
            $probeT = [string]$cf.lastProbe.t
            $srcTxt = 'confidence_state.lastProbe'
            if ($cf.lastProbe.timestamp) {
                try { $ageH = [math]::Round(($now - [DateTimeOffset]::FromUnixTimeSeconds([long][math]::Floor([double]$cf.lastProbe.timestamp))).TotalHours, 1) } catch { }
            }
            if ($null -eq $ageH -and $probeT) { try { $ageH = [math]::Round(($now - [DateTimeOffset]::Parse($probeT)).TotalHours, 1) } catch { } }
        } elseif ($cf -and $cf.baselineIp) {
            $exitIp = [string]$cf.baselineIp; $google = [string]$cf.baselineGoogleCountry; $physical = [string]$cf.baselinePhysicalCountry
            $srcTxt = 'confidence_state.baseline（无 lastProbe）'
        } elseif ($nd -and $nd.ip) {
            $exitIp = [string]$nd.ip; $google = [string]$nd.googleCountry; $physical = [string]$nd.country
            $srcTxt = 'nodes.json（兜底，更旧）'
            if ($nodes.generatedAt) { try { $ageH = [math]::Round(($now - [DateTimeOffset]::Parse([string]$nodes.generatedAt)).TotalHours, 1) } catch { } }
        }
        $verdict = ($google -and $google -ne 'FAIL' -and $google -ne 'UNKNOWN')
        $fresh = ($null -ne $ageH -and $ageH -le ($script:APH_FreshnessSec / 3600))

        # ③ 账号与密度（按出口聚合；排除陈旧绑定）
        $idents = @()
        foreach ($w in ($whoByPort[$port])) { $idents += (Resolve-Identity $w) }
        $b = $null
        if ($bind -and ($bind.PSObject.Properties.Name -contains [string]$port)) { $b = $bind.([string]$port) }
        if ($b -and $b.profile -and -not ($idents | Where-Object { $_.Name -eq [string]$b.profile })) { $idents += (Resolve-Identity ('环境:' + [string]$b.profile)) }
        $liveIdents = @($idents | Where-Object { $_.Live })
        $staleCnt = @($idents | Where-Object { -not $_.Live }).Count
        if ($px -and $densityByProxy.ContainsKey($px)) { $density = $densityByProxy[$px]; $densitySrc = 'l0_state.exit_density（按出口聚合）' }
        else { $density = $liveIdents.Count; $densitySrc = '本口自算' }

        # ④ 契约
        $expCountry = '—'; $retired = $false; $retiredBy = ''
        if ($b) {
            if ($b.expectedCountry) { $expCountry = [string]$b.expectedCountry }
            if ($b.contract_unknown) { $expCountry = '未定(contract_unknown)' }
            $k = ([string]$b.profile).ToLower()
            if ($deadNames.ContainsKey($k)) {
                $st = [string]$deadNames[$k].status
                if ($st -eq 'retired' -or $st -eq 'service_banned') { $retired = $true; $retiredBy = $st }
            }
        }

        # ⑥ 归属
        $dual = (@($liveIdents | Where-Object { $_.Kind -eq 'Antigravity' }).Count -gt 0)
        # 占位/宣传条目（订阅源名层）
        $origName = if ($pm) { [string]$pm.OrigName } else { '' }
        $placeholder = [bool]($origName -match '剩余流量|套餐到期|官网|网址|下载|交流群|公告|国内访问|距离下次重置|重置剩余|电报|@|订阅|客服')

        $rows.Add([pscustomobject]@{
            Port = $port
            # ① 端口为键 + port→proxy（live）
            ProxyName = $px
            ProxySrc  = [string]$srcByPort[$port]
            Brand     = if ($pm) { [string]$pm.Airport } else { if ($port -lt 22000) { '蜂窝' } else { '星辰' } }
            OrigName  = $origName
            Placeholder = $placeholder
            PlaceholderText = if ($placeholder) { '⚠ 占位/宣传条目' } else { '—' }
            # ② 实测 + 判国
            ExitIp = $exitIp
            GoogleCountry = if ($verdict) { $google } else { '—(无判国)' }
            GoogleRaw = $google
            Physical = $physical
            ProbeAt  = $probeT
            ProbeAgeH = $ageH
            Fresh = $fresh
            FreshText = if ($null -eq $ageH) { '无探测记录' } elseif ($fresh) { "$ageH h" } else { "⚠ $ageH h 不新鲜" }
            ProbeSrc = $srcTxt
            # ③ 账号/密度
            LiveAccounts = $density
            DensityCap = $script:APH_DensityCap
            DensityText = "$density / $($script:APH_DensityCap)"
            DensityOver = ($density -gt $script:APH_DensityCap)
            DensitySrc = $densitySrc
            AccountsText = (($idents | ForEach-Object { if ($_.Live) { $_.Name } else { '✗' + $_.Name } }) -join ' , ')
            StaleCount = $staleCnt
            # ④ 契约
            ExpectedCountry = $expCountry
            Retired = $retired
            RetiredText = if ($retired) { "retired($retiredBy)" } else { '—' }
            # ⑤ 冻结
            Pinned = [bool]($lock -and $lock.ports -and ($lock.ports.PSObject.Properties.Name -contains [string]$port))
            LockScope = if ($lock -and $lock.scope) { [string]$lock.scope.mode } else { '无锁表' }
            AutoRebuild = [bool]$sw.Enabled
            FreezeText = $(if ($sw.Enabled) { '自动重建:开 / 锁表:' + [string]$lock.scope.mode } else { '自动重建:关 / 锁表:' + [string]$lock.scope.mode })
            # ⑥ 归属
            DualEnd = $dual
            Owner = if ($dual) { '双端在册' } elseif (@($idents).Count -gt 0) { 'APH-only' } else { '未标注' }
            MeasuredIpDensity = 0
            IpDensityOver = $false
            # ⑦ 后端巡检结论（account_guard_state 逐口）
            GuardGoogle = ''
        })
    }
    # 巡检结论回填（同一次读取）
    if ($guard -and $guard.ports) {
        $gmap = @{}; foreach ($e in $guard.ports) { $gmap[[int]$e.port] = [string]$e.google }
        foreach ($r in $rows) { if ($gmap.ContainsKey($r.Port)) { $r.GuardGoogle = $gmap[$r.Port] } }
    }
    # 交叉核对：按**实测出口 IP** 聚合（用户口径「一个 IP 最多 2 个号」），与后端 exit_density 双轨呈现
    $ipAgg = @{}
    foreach ($r in $rows) { if ($r.ExitIp) { $ipAgg[$r.ExitIp] = ([int]$ipAgg[$r.ExitIp]) + [int]$r.LiveAccounts } }
    foreach ($r in $rows) {
        if ($r.ExitIp -and $ipAgg.ContainsKey($r.ExitIp)) {
            $r.MeasuredIpDensity = [int]$ipAgg[$r.ExitIp]
            $r.IpDensityOver = ($r.MeasuredIpDensity -gt $script:APH_DensityCap)
        }
    }
    $script:APH_ConfStamp = $confStamp
    return $rows
}

# 主面板「极简一行」：冻结状态 + 账本新鲜度 + 巡检结论 + 密度超限 + 不新鲜探测
function Get-PortLedgerSummary {
    $rows = @(Get-PortLedger)
    $sw = Get-AutoRebuildSwitch
    $stale = @($rows | Where-Object { -not $_.Fresh }).Count
    $over  = @($rows | Where-Object { $_.DensityOver }).Count
    $live  = @($rows | Where-Object { $_.LiveAccounts -gt 0 }).Count
    $l0 = Read-AphJson 'l0_state.json'
    $evt = if ($l0) { [int]$l0.last_event_count } else { 0 }
    $ok  = if ($l0) { [bool]$l0.last_report_ok } else { $false }
    $okText = if ($l0) { if ($ok) { 'OK' } else { "$evt 个事件" } } else { '无账本' }
    return [pscustomobject]@{
        Text = "映射冻结 $($sw.Text) · 端口账本 l0_state($(Get-AphFileStamp 'l0_state.json')) · 巡检 $okText · 密度超限 $over · 不新鲜探测 $stale/$($rows.Count)"
        Switch = $sw
        Rows = $rows
        StaleCount = $stale
        OverCount = $over
        LivePortCount = $live
        Total = $rows.Count
        EventCount = $evt
        ReportOk = $ok
    }
}

function Get-PortLedgerLockScope {
    $lock = Read-AphJson 'port_map_lock.json'
    if ($lock -and $lock.scope) { return ([string]$lock.scope.mode) + '/' + ([string]$lock.scope.total) + '口' }
    return '无锁表'
}

# ============================================================== C. 订阅刷新检查（可单测）
# 把「检测订阅刷新 → 是否允许自动重建 → 重建前后 config.yaml 字节指纹」收进一个函数，
# 便于**不启动 UI**也能对「开关=关 ⇒ 不重建、config 字节不变」做确定性验证。
function Get-ConfigFingerprint {
    $cfg = Join-Path $script:APH_Root 'config\config.yaml'
    if (-not (Test-Path -LiteralPath $cfg)) { return '无 config.yaml' }
    $i = Get-Item -LiteralPath $cfg
    return ((Get-FileHash -LiteralPath $cfg -Algorithm SHA256).Hash.Substring(0, 16) + '/' + $i.Length + 'B/' + $i.LastWriteTime.ToString('MM-dd HH:mm:ss'))
}

function Invoke-SubscriptionRefreshCheck {
    param(
        $Info,                       # Get-ProfileInfo 的返回值（需含 Write）
        [ref]$LastWrite,             # 上次记录的订阅文件写入时间
        [scriptblock]$Rebuild,       # 真正执行重建的动作（由 panel.ps1 传入 Sync-FromHoneycomb）
        [scriptblock]$Log            # 可选：日志写入（panel.ps1 传 Write-PanelEvent）
    )
    $sw = Get-AutoRebuildSwitch
    $res = [pscustomobject]@{ Action = 'none'; Rebuilt = $false; Text = ''; ConfigBefore = ''; ConfigAfter = ''; ConfigUnchanged = $true; Switch = $sw.Enabled }
    if (-not $Info -or -not $Info.Write) { return $res }
    if (-not $LastWrite.Value) { $LastWrite.Value = $Info.Write; $res.Action = 'baseline'; return $res }
    if ($Info.Write -eq $LastWrite.Value) { return $res }
    $LastWrite.Value = $Info.Write
    $res.ConfigBefore = Get-ConfigFingerprint
    if ($sw.Enabled) {
        $res.Action = 'rebuilt'
        if ($Log) { & $Log 'auto-rebuild' ('订阅刷新 ⇒ 自动重建＝开：执行重建（config 前: ' + $res.ConfigBefore + '）') }
        if ($Rebuild) { & $Rebuild }
        $res.Rebuilt = $true
        $res.ConfigAfter = Get-ConfigFingerprint
        $res.ConfigUnchanged = ($res.ConfigAfter -eq $res.ConfigBefore)
        if ($Log) { & $Log 'auto-rebuild-done' ('重建完成；config 后: ' + $res.ConfigAfter + '；是否变化=' + $res.ConfigUnchanged) }
        $res.Text = '检测到蜂窝订阅已刷新：自动重建＝开，已重新生成配置并热重载内核。'
    } else {
        $res.Action = 'skipped'
        $res.ConfigAfter = Get-ConfigFingerprint
        $res.ConfigUnchanged = ($res.ConfigAfter -eq $res.ConfigBefore)
        if ($Log) { & $Log 'auto-rebuild-skipped' ('订阅已刷新，但自动重建＝关（映射冻结生效）⇒ 未重建；config 前/后 ' + $res.ConfigBefore + ' / ' + $res.ConfigAfter + '；字节未变=' + $res.ConfigUnchanged) }
        $res.Text = '检测到蜂窝订阅已刷新：自动重建已关闭（映射冻结生效），端口映射保持不变。'
    }
    return $res
}