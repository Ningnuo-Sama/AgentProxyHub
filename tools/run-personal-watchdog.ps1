$ErrorActionPreference = 'Stop'
$python = 'C:\Users\1\AppData\Local\Programs\Python\Python314\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
$root = 'D:\GitHub\AgentProxyHub'
& $python (Join-Path $root 'tools\tun_watchdog_runner.py') --personal --interval 5
exit $LASTEXITCODE
