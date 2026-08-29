#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# VISION AI OS — cross-platform launcher (Linux / macOS / Windows-Git-Bash)
#
# Mirrors the behavior of start.bat but uses only POSIX shell commands so it
# runs unchanged on Linux and macOS. On Windows you can still use start.bat.
#
# Usage:
#   ./start.sh            # defaults to web mode
#   ./start.sh web        # FastAPI dashboard on http://localhost:8000
#   ./start.sh voice      # direct microphone mode
#   ./start.sh wake       # "Hey VISION" wake-word mode
#   ./start.sh cli        # interactive text terminal
# ─────────────────────────────────────────────────────────────────────────────
set -u

echo "==================================================="
echo "          VISION AI - SYSTEM LAUNCHER"
echo "==================================================="
echo

# ── Detect Python executable (virtualenv or system) ────────────────────────
if [ -x ".venv/bin/python" ]; then
    PYTHON_EXE=".venv/bin/python"
    echo "[*] Using virtual environment: .venv"
elif [ -x ".venv/Scripts/python.exe" ]; then
    # Git-Bash / WSL on Windows
    PYTHON_EXE=".venv/Scripts/python.exe"
    echo "[*] Using virtual environment: .venv (Windows)"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXE="python3"
    echo "[!] .venv not detected. Using system python3."
else
    PYTHON_EXE="python"
    echo "[!] .venv not detected. Using system python."
fi

# ── Parse mode (default: web) ──────────────────────────────────────────────
MODE="${1:-web}"

# ── Free port 8000 if occupied (cross-platform) ────────────────────────────
free_port_8000() {
    if command -v lsof >/dev/null 2>&1; then
        pids=$(lsof -ti tcp:8000 2>/dev/null)
    elif command -v fuser >/dev/null 2>&1; then
        pids=$(fuser 8000/tcp 2>/dev/null | tr -d ' ')
    elif command -v ss >/dev/null 2>&1; then
        pids=$(ss -ltnp 2>/dev/null | awk '/:8000 /{print $0}' | grep -oE 'pid=[0-9]+' | cut -d= -f2)
    fi
    if [ -n "${pids:-}" ]; then
        # shellcheck disable=SC2086
        kill -9 $pids >/dev/null 2>&1 || true
    fi
}

# ── Open a URL in the default browser (cross-platform) ─────────────────────
open_url() {
    url="$1"
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1 &
    elif command -v open >/dev/null 2>&1; then
        open "$url" >/dev/null 2>&1 &
    elif command -v start >/dev/null 2>&1; then
        start "$url" >/dev/null 2>&1 &
    fi
}

# ── WEB MODE ────────────────────────────────────────────────────────────────
if [ "$MODE" = "web" ]; then
    echo "[*] Starting VISION Web Dashboard..."
    echo "[*] Server: http://localhost:8000"
    echo "[*] Opening browser automatically..."
    echo

    free_port_8000

    # Open browser after a short delay (gives the server time to boot)
    (sleep 3; open_url "http://localhost:8000") &

    "$PYTHON_EXE" -m uvicorn vision.gateways.web.server:app --host 127.0.0.1 --port 8000
    EXIT_CODE=$?

# ── VOICE MODE ──────────────────────────────────────────────────────────────
elif [ "$MODE" = "voice" ]; then
    echo "[*] Launching VISION in direct Voice Mode..."
    echo "[*] Speak into your microphone to interact with VISION."
    echo
    "$PYTHON_EXE" main.py --mode voice
    EXIT_CODE=$?

# ── WAKE MODE ───────────────────────────────────────────────────────────────
elif [ "$MODE" = "wake" ]; then
    echo "[*] Launching VISION in Wake-Word Mode..."
    echo "[*] Say \"Hey VISION\" to activate."
    echo
    "$PYTHON_EXE" main.py --mode wake
    EXIT_CODE=$?

# ── CLI MODE ────────────────────────────────────────────────────────────────
elif [ "$MODE" = "cli" ]; then
    echo "[*] Launching VISION in CLI Mode..."
    echo
    "$PYTHON_EXE" main.py --mode cli
    EXIT_CODE=$?

else
    echo "[!] Unknown mode: $MODE"
    echo "[*] Available modes: web, voice, wake, cli"
    echo "[*] Usage: ./start.sh [mode]"
    EXIT_CODE=1
fi

if [ "${EXIT_CODE:-0}" -ne 0 ]; then
    echo
    echo "[!] VISION stopped with code: ${EXIT_CODE}"
fi
exit "${EXIT_CODE:-0}"
