$ErrorActionPreference = 'Stop'
$health = 'http://127.0.0.1:8767/health'
try {
  $response = Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 1
  if ($response.StatusCode -eq 200) { Write-Output 'existing_healthy_adapter_reused'; exit 0 }
} catch { }
$port = Get-NetTCPConnection -LocalPort 8767 -State Listen -ErrorAction SilentlyContinue
if ($port) { throw "port_8767_occupied_by_pid_$($port[0].OwningProcess)" }
$python = 'C:\Users\1\AppData\Local\Programs\Python\Python314\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
$root = 'D:\GitHub\AgentProxyHub'
Start-Process -FilePath $python -ArgumentList (Join-Path $root 'tools\eva_h5_adapter.py') -WorkingDirectory $root -WindowStyle Hidden
for ($i = 0; $i -lt 10; $i++) {
  Start-Sleep -Milliseconds 300
  try { $response = Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 1; if ($response.StatusCode -eq 200) { Write-Output 'adapter_started'; exit 0 } } catch { }
}
throw 'adapter_health_timeout'
