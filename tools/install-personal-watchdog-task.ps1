$ErrorActionPreference = 'Stop'
$taskName = 'AgentProxyHub-Personal-TUN-Watchdog'
$runner = 'D:\GitHub\AgentProxyHub\tools\run-personal-watchdog.ps1'
if (-not (Test-Path -LiteralPath $runner)) { throw 'watchdog_runner_missing' }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Days 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description '仅监护AgentProxyHub个人21919；不启动业务内核，不改变账号绑定' -Force
Write-Output "installed:$taskName"
