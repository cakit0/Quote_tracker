@echo off
title HAWE Quote Tracker
color 0C

echo.
echo  ============================================
echo   HAWE Quote Tracker - Starting...
echo  ============================================
echo.

:: Run from the folder this batch file lives in (e.g. a OneDrive folder).
cd /d "%~dp0"

:: Locate Python (prefer 'python', fall back to 'py' launcher).
set PYTHON=
python --version >nul 2>&1 && set PYTHON=python
if not defined PYTHON (
    py --version >nul 2>&1 && set PYTHON=py
)
if not defined PYTHON (
    echo  ERROR: Python is not installed or not on PATH.
    echo.
    echo  Install Python 3.9+ from https://www.python.org/downloads/
    echo  and tick "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)

echo  Checking dependencies (first run only)...
%PYTHON% -c "import pdfplumber, openpyxl" >nul 2>&1
if %errorlevel% neq 0 (
    echo  Installing required packages...
    %PYTHON% -m pip install --user -r requirements.txt
    if %errorlevel% neq 0 (
        echo.
        echo  ERROR: Could not install packages. Check your internet connection.
        pause
        exit /b 1
    )
)

:: Drag-and-drop is optional; install it quietly if missing.
%PYTHON% -c "import tkinterdnd2" >nul 2>&1 || %PYTHON% -m pip install --user tkinterdnd2 >nul 2>&1

echo  Launching...
echo.
%PYTHON% -m quote_tracker.main
if %errorlevel% neq 0 pause
