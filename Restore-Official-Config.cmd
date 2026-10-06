@echo off
setlocal
pushd "%~dp0"
call "%~dp0tps.cmd" official-audit --restore
pause
popd
