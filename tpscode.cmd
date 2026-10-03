@echo off
rem Managed by Codex TPS
setlocal
set "TPSCODE_NEAR=%~dp0"
set "TPSCODE_PROFILE=%~dp0..\..\AppData\Local\CodexTPS\app\"
set "TPSCODE_ENV=%LOCALAPPDATA%\CodexTPS\app\"
set "TPSCODE_APP=%TPSCODE_NEAR%"
if exist "%TPSCODE_APP%codex_tps.py" goto app_found
set "TPSCODE_APP=%TPSCODE_PROFILE%"
if exist "%TPSCODE_APP%codex_tps.py" goto app_found
set "TPSCODE_APP=%TPSCODE_ENV%"
if exist "%TPSCODE_APP%codex_tps.py" goto app_found
echo Could not locate Codex TPS. Run install-command.ps1 from the tool folder.
echo Checked: "%TPSCODE_NEAR%codex_tps.py"
echo Checked: "%TPSCODE_PROFILE%codex_tps.py"
echo Checked: "%TPSCODE_ENV%codex_tps.py"
exit /b 1
:app_found
if "%~1"=="" goto open_desktop
call "%TPSCODE_APP%tps.cmd" %*
exit /b %errorlevel%
:open_desktop
call "%TPSCODE_APP%Start-Codex-TPS.cmd"
exit /b %errorlevel%
