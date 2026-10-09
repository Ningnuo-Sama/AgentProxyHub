# 只读：输出 Flow 号池里每个 Google 账号当前绑定的出口端口（JSON）
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security | Out-Null
$p = Join-Path $env:LOCALAPPDATA 'FlowTools/accounts.json'
$hex = (Get-Content -Raw -LiteralPath $p).Trim()
if ($hex[0] -eq '0') {
    $b = [byte[]]::new($hex.Length / 2)
    for ($i = 0; $i -lt $b.Length; $i++) { $b[$i] = [Convert]::ToByte($hex.Substring($i * 2, 2), 16) }
    $json = [System.Text.Encoding]::UTF8.GetString([System.Security.Cryptography.ProtectedData]::Unprotect($b, $null, 'CurrentUser'))
} else { $json = $hex }
$acc = $json | ConvertFrom-Json
$out = foreach ($a in $acc) {
    $m = [regex]::Match([string]$a.boundProxy, ':(\d+)$')
    [pscustomobject]@{ email = $a.email; port = if ($m.Success) { [int]$m.Groups[1].Value } else { 0 }; pinned = $a.pinnedExitIp }
}
$out | ConvertTo-Json -Depth 4 -Compress
