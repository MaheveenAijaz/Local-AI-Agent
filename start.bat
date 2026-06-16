@echo off
echo ========================================
echo    LOCAL AI AGENT LAUNCHER
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed or not in PATH!
    echo Please install Python from python.org
    pause
    exit /b
)

REM Check if Ollama is installed
ollama --version >nul 2>&1
if errorlevel 1 (
    echo Ollama is not installed!
    echo Please download and install from: https://ollama.ai/download
    pause
    exit /b
)

echo Starting Local AI Agent...
echo.

REM Check if qwen2.5:0.5b is installed
echo Checking for qwen2.5:0.5b model...
ollama list | find "qwen2.5:0.5b" >nul
if errorlevel 1 (
    echo Model not found. Pulling qwen2.5:0.5b...
    start cmd /k "ollama pull qwen2.5:0.5b"
) else (
    echo ✅ Model qwen2.5:0.5b is already installed
)

REM Start Flask app
echo Starting Flask app...
echo.
echo Flask app will start in a new window...
start cmd /k "cd /d C:\Local_AI_Agent && python app.py"

echo.
echo ========================================
echo ✅ All services starting!
echo ========================================
echo.
echo Access the app at: http://127.0.0.1:8080
echo.
echo If you see connection errors, run debug.py to troubleshoot
echo.
pause