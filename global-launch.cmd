@echo off
rem Managed by Codex TPS
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tpscode-launch.ps1" %*
exit /b %errorlevel%
