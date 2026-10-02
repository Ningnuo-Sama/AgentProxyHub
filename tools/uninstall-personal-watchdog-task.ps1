$ErrorActionPreference = 'Stop'
$taskName = 'AgentProxyHub-Personal-TUN-Watchdog'
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Output "removed:$taskName"
