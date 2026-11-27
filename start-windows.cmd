@echo off
setlocal
cd /d "%~dp0"
call run-python-windows.cmd %*
set "workbench_exit=%errorlevel%"
if not "%workbench_exit%"=="0" pause
exit /b %workbench_exit%
