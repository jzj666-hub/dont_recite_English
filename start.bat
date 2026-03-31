@echo off
chcp 65001 >nul
title English Dictionary and Translator

echo ========================================
echo English Dictionary and Translator
echo ========================================
echo.

echo Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python and try again
    pause
    exit /b 1
)

echo Python is installed
echo.

echo Checking dependencies...
pip show PyQt6 >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo ERROR: Failed to install dependencies
        pause
        exit /b 1
    )
    echo Dependencies installed successfully
) else (
    echo Dependencies are already installed
)

echo.
echo Starting application...
echo.

python search.py

if %errorlevel% neq 0 (
    echo.
    echo Application exited with an error
    pause
    exit /b 1
)

echo.
echo Application closed
pause
