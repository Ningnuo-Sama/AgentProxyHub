@echo off
chcp 936 >nul
title AgentProxyHub - 停止服务
cd /d "%~dp0\.."

echo 正在安全停止 AgentProxyHub 进程与内核监听...
taskkill /f /im mihomo.exe >nul 2>&1
echo [OK] 已停止内核进程。
timeout /t 2 >nul
exit
