@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 goto use_py
python -c "import sys; sys.exit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 goto use_python
echo Python 3.11 or newer was not found.
echo Install Python from python.org, enable Add python.exe to PATH, then reopen this window.
exit /b 1
:use_py
py -3 launch.py %*
exit /b %errorlevel%
:use_python
python launch.py %*
exit /b %errorlevel%
