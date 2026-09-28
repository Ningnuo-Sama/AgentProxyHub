@echo off
chcp 936 >nul
title AgentProxyHub - 打开控制面板
cd /d "%~dp0\.."
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "ui\panel.ps1"
exit
