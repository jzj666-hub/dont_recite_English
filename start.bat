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
set "DEP_MISSING=0"
pip show PyQt6 >nul 2>&1 || set DEP_MISSING=1
pip show uvicorn >nul 2>&1 || set DEP_MISSING=1
pip show fastapi >nul 2>&1 || set DEP_MISSING=1
pip show edge-tts >nul 2>&1 || set DEP_MISSING=1

if %DEP_MISSING% equ 1 (
    echo Installing missing dependencies...
    echo Upgrading pip first...
    python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo Installing requirements...
    python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
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
echo Starting TTS Backend Server...
start /b python tts_server.py
timeout /t 2 /nobreak >nul

echo Starting main application...
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