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

echo [1/3] 正在校验本地端口池与场景规则...

echo [2/3] 拉起后台 mihomo 内核（silent-start.vbs，幂等：已在跑则跳过）...
cscript //nologo "scripts\silent-start.vbs"

echo [3/3] 正在唤起桌面控制面板...
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "ui\panel.ps1"

echo.
echo ========================================================
echo  AgentProxyHub 已成功启动！
echo  - 桌面控制面板已唤出 (可点击关闭最小化至托盘)
echo  - 手机/局域网分流网关已在后台静默就绪
echo ========================================================
timeout /t 3 >nul
exit
