@echo off
setlocal
pushd "%~dp0"
call "%~dp0tps.cmd" profiles-audit --restore
pause
popd
