@echo off
title HAWE Quote Tracker
setlocal

:: Run from the folder this batch file lives in (e.g. a OneDrive folder).
cd /d "%~dp0"

:: Locate Python (prefer 'python', fall back to the 'py' launcher).
set PYTHON=
python --version >nul 2>&1 && set PYTHON=python
if not defined PYTHON (
    py --version >nul 2>&1 && set PYTHON=py
)
if not defined PYTHON (
    echo.
    echo  Python was not found on this PC.
    echo.
    echo  Install Python 3.9 or newer from https://www.python.org/downloads/
    echo  and tick "Add Python to PATH" during setup, then run this again.
    echo.
    pause
    exit /b 1
)

:: Install requirements on the first run only (quiet unless something fails).
%PYTHON% -c "import pdfplumber, openpyxl" >nul 2>&1
if %errorlevel% neq 0 (
    echo Setting up for first use, this takes a minute...
    %PYTHON% -m pip install --user --quiet -r requirements.txt
    if %errorlevel% neq 0 (
        echo.
        echo  Setup failed - check your internet connection and try again.
        echo.
        pause
        exit /b 1
    )
)

:: Drag-and-drop support is optional; install quietly if missing.
%PYTHON% -c "import tkinterdnd2" >nul 2>&1 || %PYTHON% -m pip install --user --quiet tkinterdnd2 >nul 2>&1

:: Launch with pythonw (the windowless interpreter) so no console stays open.
:: 'start' returns immediately, letting this window close right away.
if /i "%PYTHON%"=="py" (
    start "" %PYTHON% -w -m quote_tracker.main
) else (
    start "" pythonw -m quote_tracker.main 2>nul || start "" %PYTHON% -m quote_tracker.main
)
exit /b 0
