@echo off
rem AgentProxyHub headless runner
cd /d "%~dp0"
if not exist "%~dp0logs" mkdir "%~dp0logs"

set "CORE_EXE=%~dp0bin\mihomo.exe"
if not exist "%CORE_EXE%" set "CORE_EXE=%~dp0mihomo.exe"

set "CONF_FILE=%~dp0config\config.yaml"
if not exist "%CONF_FILE%" set "CONF_FILE=%~dp0config.yaml"

"%CORE_EXE%" -d "%~dp0." -f "%CONF_FILE%" > "%~dp0logs\bridge.log" 2>&1