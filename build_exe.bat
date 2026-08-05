@echo off
title Build HAWE Quote Tracker EXE
color 0C
cd /d "%~dp0"

echo.
echo  ============================================
echo   Building QuoteTracker.exe (standalone)
echo  ============================================
echo.
echo  This produces dist\QuoteTracker.exe - a single file that runs on any
echo  Windows PC WITHOUT Python installed. Build takes a few minutes.
echo.

set PYTHON=
python --version >nul 2>&1 && set PYTHON=python
if not defined PYTHON ( py --version >nul 2>&1 && set PYTHON=py )
if not defined PYTHON (
    echo  ERROR: Python not found. Install it from https://www.python.org/downloads/
    pause & exit /b 1
)

echo  Installing build tools and dependencies...
%PYTHON% -m pip install --upgrade pyinstaller -r requirements.txt
if %errorlevel% neq 0 ( echo  ERROR: pip install failed. & pause & exit /b 1 )

echo  Running PyInstaller...
%PYTHON% -m PyInstaller ^
    --noconfirm --clean --onefile --windowed ^
    --name QuoteTracker ^
    --icon assets\icon.ico ^
    --version-file assets\version_info.txt ^
    --add-data "assets;assets" ^
    --collect-all tkinterdnd2 ^
    --collect-all pdfplumber ^
    --collect-all pdfminer ^
    --collect-submodules openpyxl ^
    run.py

if %errorlevel% neq 0 ( echo  ERROR: build failed. & pause & exit /b 1 )

echo.
echo  ============================================
echo   Done.  ->  dist\QuoteTracker.exe
echo  ============================================
echo.
echo  Copy QuoteTracker.exe to your OneDrive Quoting folder and double-click it.
echo  The database (hawe_quotes.db) is created next to the EXE on first run.
echo.
pause
