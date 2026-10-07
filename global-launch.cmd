@echo off
rem Managed by Codex TPS
setlocal
pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tpscode-launch.ps1" %*
exit /b %errorlevel%
