@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-personal-watchdog.ps1"
exit /b %ERRORLEVEL%
