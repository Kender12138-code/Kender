@echo off
REM Double-click to start the farm shop ReAct demo
REM This uses the managed WorkBuddy venv Python that has all dependencies installed.

cd /d "%~dp0"

set PYTHON="C:\Users\10215\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set PORT=7862

%PYTHON% -c "import sys; print('Using', sys.executable)"

%PYTHON% farm_react_app.py

if errorlevel 1 (
    echo.
    echo If the port %PORT% is still in TIME_WAIT, try:
    echo   set GRADIO_SERVER_PORT=7863
    echo   run_demo.bat
    echo.
    pause
)
