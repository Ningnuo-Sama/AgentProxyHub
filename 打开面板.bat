@echo off
chcp 936 >nul
cd /d "%~dp0"
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0ui\panel.ps1"
exit