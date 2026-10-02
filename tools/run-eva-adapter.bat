@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-eva-adapter.ps1"
exit /b %ERRORLEVEL%
