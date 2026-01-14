@echo off
REM Perfect Web Clone - Backend Startup Script for Windows
REM Windows 后端启动脚本

echo ==========================================
echo Perfect Web Clone Backend (Windows)
echo ==========================================

cd /d "%~dp0"

REM Check for virtual environment
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -q -r requirements.txt

REM Install Playwright browser if not already installed
echo Checking Playwright browser...
playwright install chromium

REM Check for .env file
if not exist ".env" (
    if exist ".env.example" (
        echo Creating .env from .env.example...
        copy .env.example .env
        echo Please edit .env to add your ANTHROPIC_API_KEY
    ) else (
        echo Warning: No .env file found. Create one with ANTHROPIC_API_KEY.
    )
)

REM Start the server
echo.
if "%PORT%"=="" set PORT=5100

echo Starting server on http://localhost:%PORT%
echo API docs: http://localhost:%PORT%/docs
echo.

python main.py
