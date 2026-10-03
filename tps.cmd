@echo off
setlocal
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 "%~dp0codex_tps.py" %*
exit /b %errorlevel%
:use_python
python "%~dp0codex_tps.py" %*
exit /b %errorlevel%
