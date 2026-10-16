$ErrorActionPreference = 'Stop'
$python = 'C:\Users\1\AppData\Local\Programs\Python\Python314\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
# t37: $root 原硬编码源码仓（与其他 task 脚本不一致）修为「环境变量 > 运行副本 > 源码仓」。
$rt  = 'D:\Program Files\AgentProxyHub'
$src = 'D:\GitHub\AgentProxyHub'
$root = if ($env:APHUB_ROOT) { $env:APHUB_ROOT }
        elseif (Test-Path -LiteralPath (Join-Path $rt 'config')) { $rt }
        else { $src }
& $python (Join-Path $root 'tools\tun_watchdog_runner.py') --personal --interval 5
exit $LASTEXITCODE
