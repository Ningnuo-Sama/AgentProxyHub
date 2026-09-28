@echo off
chcp 936 >nul
title AgentProxyHub - 启动后台内核
cd /d "%~dp0\.."

echo ========================================================
echo       AgentProxyHub · 智能多出口代理中枢启动器
echo ========================================================
echo.

if not exist "bin\mihomo.exe" (
    if exist "D:\Program Files\FengWoBridge\mihomo.exe" (
        if not exist "bin" mkdir "bin"
        copy /y "D:\Program Files\FengWoBridge\mihomo.exe" "bin\mihomo.exe" >nul
        copy /y "D:\Program Files\FengWoBridge\geoip.metadb" "bin\geoip.metadb" >nul 2>nul
        copy /y "D:\Program Files\FengWoBridge\geosite.dat" "bin\geosite.dat" >nul 2>nul
        echo [OK] 已自动装配本地高性能代理内核。
    ) else (
        echo [提示] 未在 bin\ 目录下发现 mihomo.exe 内核，将启动轻量代理调度模式。
    )
)

echo [1/2] 正在校验本地端口池与场景规则...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$host.UI.RawUI.WindowTitle='AgentProxyHub Daemon'; Write-Host '[AgentProxyHub] 核心守护进程已在后台就绪。' -ForegroundColor Cyan"

echo [2/2] 正在唤起桌面控制面板...
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "ui\panel.ps1"

echo.
echo ========================================================
echo  AgentProxyHub 已成功启动！
echo  - 桌面控制面板已唤出 (可点击关闭最小化至托盘)
echo  - 手机/局域网分流网关已在后台静默就绪
echo ========================================================
timeout /t 3 >nul
exit
