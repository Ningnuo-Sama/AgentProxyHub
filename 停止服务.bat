@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
echo ========================================================
echo       AgentProxyHub - 停止业务内核（不碰个人出海内核）
echo ========================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$own = Get-CimInstance Win32_Process -Filter \"Name='mihomo.exe'\" | Where-Object { $_.ExecutablePath -like 'D:\Program Files\AgentProxyHub\*' -or $_.ExecutablePath -like ($PWD.Path + '\*') }; if ($own) { $own | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Write-Host ('[OK] 已停止业务内核 ' + $own.Count + ' 个进程。') } else { Write-Host '[提示] 未发现本项目路径下的 mihomo 业务内核。' }"
echo.
timeout /t 2 >nul
exit
