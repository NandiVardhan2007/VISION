@echo off
setlocal EnableExtensions
title VISION Autonomous AI Voice ^& OS System

:: Always run from the script's own folder so relative paths (.venv, main.py)
:: resolve no matter where the launcher is invoked from.
cd /d "%~dp0"
cls

echo ===================================================
echo           VISION AI - SYSTEM LAUNCHER
echo ===================================================
echo.

:: ── Resolve a WORKING Python interpreter ─────────────────────────
:: A .venv can exist yet be broken if the base Python it was built on was
:: uninstalled/moved (its python.exe is only a stub). So we test that the
:: interpreter actually runs before trusting it, then fall back gracefully.
set "PYTHON_EXE="

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" --version >nul 2>&1 && (
        set "PYTHON_EXE=.venv\Scripts\python.exe"
        echo [*] Using virtual environment: .venv
    ) || (
        echo [!] .venv is present but broken - its base Python was moved or uninstalled.
        echo [!] Recreate it with:  py -3 -m venv .venv ^&^& .venv\Scripts\python -m pip install -r requirements.txt
        echo [*] Falling back to system Python for now...
    )
)

if not defined PYTHON_EXE (
    py -3 --version >nul 2>&1 && (
        for /f "delims=" %%p in ('py -3 -c "import sys;print(sys.executable)"') do set "PYTHON_EXE=%%p"
        echo [*] Using system Python via the py launcher.
    )
)

if not defined PYTHON_EXE (
    python --version >nul 2>&1 && (
        set "PYTHON_EXE=python"
        echo [*] Using 'python' from PATH.
    )
)

if not defined PYTHON_EXE (
    echo [!] No working Python interpreter was found on this system.
    echo [*] Install Python 3.10+ from https://www.python.org/downloads/ and re-run this script.
    echo.
    pause
    exit /b 1
)
echo.

:: Parse mode from argument (default: web)
set "MODE=web"
if not "%~1"=="" set "MODE=%~1"

:: ── WEB MODE: Launch FastAPI server + open browser dashboard ──
if /i "%MODE%"=="web" (
    echo [*] Starting VISION Web Dashboard...
    echo [*] Server: http://localhost:8000
    echo [*] Opening browser automatically...
    echo.

    :: Free port 8000 if previously occupied
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
        taskkill /f /pid %%a >nul 2>&1
    )

    :: Open browser after a short delay (gives server time to boot)
    start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"

    :: Start uvicorn web server (blocking)
    "%PYTHON_EXE%" -m uvicorn vision.gateways.web.server:app --host 127.0.0.1 --port 8000
    goto END
)

:: ── VOICE MODE: Direct microphone listening ──
if /i "%MODE%"=="voice" (
    echo [*] Launching VISION in direct Voice Mode...
    echo [*] Speak into your microphone to interact with VISION.
    echo.
    "%PYTHON_EXE%" main.py --mode voice
    goto END
)

:: ── WAKE MODE: Hands-free "Hey VISION" trigger ──
if /i "%MODE%"=="wake" (
    echo [*] Launching VISION in Wake-Word Mode...
    echo [*] Say "Hey VISION" to activate.
    echo.
    "%PYTHON_EXE%" main.py --mode wake
    goto END
)

:: ── CLI MODE: Interactive text terminal ──
if /i "%MODE%"=="cli" (
    echo [*] Launching VISION in CLI Mode...
    echo.
    "%PYTHON_EXE%" main.py --mode cli
    goto END
)

echo [!] Unknown mode: %MODE%
echo [*] Available modes: web, voice, wake, cli
echo [*] Usage: start.bat [mode]
echo.

:END
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] VISION stopped with code: %ERRORLEVEL%
    pause
)
