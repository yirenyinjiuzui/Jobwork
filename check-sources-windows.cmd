@echo off
setlocal
cd /d "%~dp0"
call run-python-windows.cmd --check %*
exit /b %errorlevel%
