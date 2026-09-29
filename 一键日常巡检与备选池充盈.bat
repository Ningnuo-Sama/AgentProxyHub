@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
title AgentProxyHub 出口巡检与多场景测绘
echo ========================================================
echo   AgentProxyHub · 一键日常巡检与多场景测绘
echo ========================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0core\gen-report.ps1" -RootDir "%~dp0."
echo.
pause