@echo off
setlocal
pushd "%~dp0"
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%~dp0launch.pyw"
    popd
    exit /b 0
)
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0launch.pyw"
    popd
    exit /b 0
)
where python >nul 2>nul
if not errorlevel 1 (
    python "%~dp0launch.pyw" profiles-audit
    popd
    exit /b 0
)
echo Python 3.11+ with tkinter is required. See README.md.
pause
popd
exit /b 1
