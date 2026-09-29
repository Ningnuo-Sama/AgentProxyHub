@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
echo ========================================================
echo       AgentProxyHub · 停止后台代理内核
echo ========================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Process -Name mihomo -ErrorAction SilentlyContinue | Stop-Process -Force; '已安全停止 mihomo 代理内核进程。'"
echo.
timeout /t 2 >nul
exit