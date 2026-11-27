@echo off
setlocal
cd /d "%~dp0"
call run-python-windows.cmd --data-tools %*
set "workbench_exit=%errorlevel%"
pause
exit /b %workbench_exit%
