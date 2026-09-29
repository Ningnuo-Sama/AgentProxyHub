@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
echo ========================================================
echo   AgentProxyHub · 安装开机自启（后台静默运行）
echo ========================================================
echo.
if not exist "%~dp0silent-start.vbs" (
    echo [错误] 启动组件缺失（silent-start.vbs）
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d='%~dp0'.TrimEnd('\'); $t=Join-Path $d 'silent-start.vbs'; $p=Join-Path ([Environment]::GetFolderPath('Startup')) 'AgentProxyHub.lnk'; $s=New-Object -ComObject WScript.Shell; $l=$s.CreateShortcut($p); $l.TargetPath=$t; $l.WorkingDirectory=$d; $l.Description='AgentProxyHub 代理中枢后台静默自启'; $ico=Join-Path $d 'assets\app.ico'; if (Test-Path $ico) { $l.IconLocation=$ico+',0' }; $l.Save(); if (Test-Path $p) { '安装成功: ' + $p } else { '安装失败' }"
echo.
echo [完成] 已加入 Windows 开机自启：系统登录后将自动静默运行 AgentProxyHub。
echo        如需取消，请双击运行「取消开机自启.bat」。
echo.
pause