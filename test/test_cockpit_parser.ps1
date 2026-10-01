$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '..\ui\panel.ps1'
$tokens = $null
$errors = $null
$raw = [System.IO.File]::ReadAllText((Resolve-Path $scriptPath), [System.Text.Encoding]::UTF8)
[System.Management.Automation.Language.Parser]::ParseInput($raw, [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count -gt 0) { throw ($errors | ForEach-Object Message | Out-String) }
$required = @('GATEWAY OBSERVATORY', 'LIVE INTELLIGENCE STREAM', 'ENGINEER // DIRECTIVE', 'Convert-GatewayLine', 'Import-GatewayDigest', 'cockpit_rules.json', 'BtnGlmDigest')
$text = Get-Content -LiteralPath $scriptPath -Raw -Encoding UTF8
foreach ($needle in $required) {
    if ($text.IndexOf($needle, [System.StringComparison]::Ordinal) -lt 0) { throw "missing cockpit contract: $needle" }
}
'cockpit parser contract OK'
