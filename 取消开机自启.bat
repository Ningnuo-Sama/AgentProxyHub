@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
echo ========================================================
echo   AgentProxyHub · 取消开机自启
echo ========================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Join-Path ([Environment]::GetFolderPath('Startup')) 'AgentProxyHub.lnk'; if (Test-Path $p) { Remove-Item -LiteralPath $p -Force; '已移除: ' + $p } else { '未检测到自启项，无需移除。' }"
echo.
echo [完成] 开机自启已取消。
echo.
pause