# VISION AI OS

> Standalone Autonomous AI Multimodal Operating System — voice, web dashboard, and CLI.
> **Runs identically on Windows, Linux, and macOS.**

VISION is a self-contained AI assistant that can talk, listen, browse, control
applications, manage files, send messages, run terminals, and more. It was
originally built on Windows and is now fully **OS-independent**: every
platform-specific call (opening files, locking the screen, pinging, printing,
playing sounds, launching terminals) is routed through a single abstraction
module — `vision/platform.py` — which detects the OS and uses the right backend.

---

## ✨ Highlights

- 🗣️ **Voice Mode** — mic → STT → LLM → tool calls → TTS playback
- 💬 **Wake-Word Mode** — "Hey VISION" hands-free trigger
- 🌐 **Web Dashboard** — FastAPI + WebSocket UI at `http://localhost:8000`
- ⌨️ **CLI Mode** — interactive text terminal
- 🧰 **159 built-in tools** — files, system, network, hardware, printer, media,
  reminders, WhatsApp, remote server, code execution, and more
- 🔒 **Cross-platform** — no Windows-only calls leak into runtime

---

## 🖥️ Supported Platforms

| Feature | Windows | Linux | macOS |
| --- | --- | --- | --- |
| App / file open | `os.startfile` | `xdg-open` | `open` |
| Lock screen | `LockWorkStation` | `loginctl` / `gnome-screensaver` | `pmset` / `lock` |
| Shutdown / restart | `shutdown.exe` | `systemctl` / `loginctl` | `osascript` / `pmset` |
| Ping / WiFi | `ping -n` / `netsh` | `ping -c` / `nmcli` | `ping -c` / `airport` |
| Sound chime | `winsound` | `paplay` / `aplay` | `afplay` |
| Print | Win32 GDI | CUPS `lp` / `lpr` | CUPS `lp` / `lpr` |
| Terminal launch | `cmd.exe` | `gnome-terminal` / `xterm` | `Terminal.app` |

Windows-only Python packages (`pywin32`, `pycaw`, `comtypes`, `PyGetWindow`,
`screen-brightness-control`) are declared in `requirements.txt` with
`sys_platform == "win32"`, so `pip install` **succeeds on Linux/macOS** even
without them. The app degrades gracefully when an optional desktop/audio
dependency (e.g. `pyautogui`, `pyperclip`, `sounddevice`) isn't installed.

---

## 📋 Requirements

- **Python 3.10+** (tested on 3.10 / 3.11)
- **Git**
- On Linux, for full desktop features: `xdg-utils`, a notification daemon, and
  (optional) `gnome-terminal` / `xterm`, plus `lp`/`lpr` (CUPS) for printing
- On Linux/macOS, for voice: PortAudio + `sounddevice` (the wake-word/voice
  engines import `sounddevice`)

---

## 🚀 Installation

### 1. Clone

```bash
git clone https://github.com/NandiVardhan2007/JARVIS.git
cd JARVIS
```

### 2. Create a virtual environment

```bash
# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
```

> ⚠️ The repo previously shipped with a **Windows-built** `.venv` (Python 3.10,
> `C:\Python310`). That virtualenv is unusable on Linux/macOS — always create a
> fresh one as shown above.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure API keys

Copy the example env file and fill in your keys:

```bash
cp .env.example .env
```

Edit `.env` and set at least the provider keys you intend to use
(`GROQ_API_KEY`, `CARTESIA_API_KEY`, `GEMINI_API_KEY`, etc.). **Never commit
your real `.env`** — it is git-ignored.

---

## ▶️ Running VISION

Use the cross-platform launcher:

```bash
# Linux / macOS
./start.sh            # defaults to web mode
./start.sh web        # FastAPI dashboard at http://localhost:8000
./start.sh voice      # direct microphone mode
./start.sh wake       # "Hey VISION" wake-word mode
./start.sh cli        # interactive text terminal

# Windows
start.bat [web|voice|wake|cli]
```

Or run directly with Python:

```bash
# Web dashboard
python -m uvicorn vision.gateways.web.server:app --host 127.0.0.1 --port 8000

# Voice / wake / cli
python main.py --mode voice
python main.py --mode wake
python main.py --mode cli
```

The web dashboard opens automatically in your default browser (3s after launch).

---

## 🧪 Tests

```bash
pytest tests/ -q
```

Tests are OS-aware: desktop/audio tests (`pyautogui`, `pyperclip`,
`sounddevice`, `screen-brightness-control`) **skip automatically** when their
optional dependency is missing, so the suite is green on any platform. On a
minimal Linux box you can expect ~95 passed, a handful skipped, with only the
wake-word test needing `sounddevice`+PortAudio.

---

## 🗂️ Project Layout

```
vision/
  platform.py            # OS abstraction layer (IS_WINDOWS / IS_MACOS / IS_LINUX)
  tools/                 # 159 tool implementations (all OS-calls via platform.py)
  core/                  # engine, reminder daemon, wake-word
  gateways/web/          # FastAPI dashboard + WebSocket
  cognitive/             # LLM / STT / TTS providers
  memory/                # RAG, working memory, task tracker
  config.py              # central configuration (reads .env)
main.py                  # CLI / voice / wake entry point
start.sh / start.bat     # cross-platform launchers
requirements.txt         # deps (Windows-only ones gated to win32)
```

---

## 🔧 How cross-platform support works

All OS-specific logic lives in **`vision/platform.py`**. Tools never call
`os.startfile`, `ctypes.windll`, `winsound`, `netsh`, etc. directly — they call
helpers like `open_path()`, `lock_workstation()`, `ping_host()`,
`play_chime()`, `open_terminal()`, `empty_trash()`. Each helper branches on the
detected platform and falls back safely when a backend is unavailable.

To add a new OS-specific behavior, extend `vision/platform.py` (add the
`IS_WINDOWS` / `IS_MACOS` / `IS_LINUX` branch) rather than scattering
`if platform.system() == ...` checks across tool files.

---

## 📄 License

See repository for license details.
