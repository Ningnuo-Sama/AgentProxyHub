@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
title AgentProxyHub 启动服务
echo ========================================================
echo       AgentProxyHub · 智能多出口代理调度中枢
echo ========================================================
echo.

if not exist "%~dp0bin\mihomo.exe" (
    if exist "%~dp0mihomo.exe" (
        rem ok
    ) else (
        echo [错误] 未在 bin\ 目录下发现 mihomo.exe 内核！
        pause
        exit /b 1
    )
)

if not exist "%~dp0config\config.yaml" (
    if not exist "%~dp0config.yaml" (
        echo [提示] 尚未生成配置文件，正在调用 core\gen-config.ps1...
        powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0core\gen-config.ps1" -RootDir "%~dp0."
    )
)

echo [1/2] 正在静默拉起后台代理内核...
cscript //nologo "%~dp0silent-start.vbs"

echo [2/2] 正在打开控制面板...
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0ui\panel.ps1"

echo.
echo ========================================================
echo  AgentProxyHub 已启动完成！
echo  - SOCKS5 出口: 21001-21080 (蜂窝) / 22001-22045 (星辰)
echo  - 智能分流总线: 39999 (手机/局域网)
echo  - 桌面控制面板已唤出 (可随时关闭或最小化至系统托盘)
echo ========================================================
timeout /t 3 >nul
exit