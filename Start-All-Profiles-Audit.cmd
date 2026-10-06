@echo off
setlocal
pushd "%~dp0"
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%~dp0launch.pyw" profiles-audit
    popd
    exit /b 0
)
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0launch.pyw" profiles-audit
    popd
    exit /b 0
)
call "%~dp0tps.cmd" profiles-audit
popd
exit /b %errorlevel%
