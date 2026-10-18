"""
CareerPulse Silent Background Service & Autostart.
100% Windowless via pythonw.exe - Zero console windows, zero terminal popups.
Serves the FastAPI dashboard on 127.0.0.1:8000 and monitors system sleep/wake events.
"""

import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import webbrowser

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"

ROOT_DIR = Path(__file__).resolve().parent.parent

# Set ProactorEventLoopPolicy immediately on Windows for full subprocess/Playwright support
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

PYTHONW = sys.executable
if not PYTHONW.lower().endswith("pythonw.exe"):
    p_dir = Path(sys.executable).parent
    cand = p_dir / "pythonw.exe"
    if cand.exists():
        PYTHONW = str(cand)
    else:
        PYTHONW = "pythonw.exe"


def is_port_open(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def open_browser_when_ready():
    # Wait up to 15 seconds for server to be ready, then open browser
    for _ in range(30):
        time.sleep(0.5)
        if is_port_open(HOST, PORT):
            break
    webbrowser.open(URL)


def start_lid_monitor():
    # Launch lid_monitor.py via pythonw.exe (protected by internal Win32 named mutex against duplicates)
    lid_script = ROOT_DIR / "scripts" / "lid_monitor.py"
    if lid_script.exists():
        CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen(
            [PYTHONW, str(lid_script)],
            cwd=str(ROOT_DIR),
            creationflags=CREATE_NO_WINDOW,
            close_fds=True,
        )


def main():
    os.chdir(str(ROOT_DIR))
    sys.path.insert(0, str(ROOT_DIR))
    sys.path.insert(0, str(ROOT_DIR / "src"))

    if is_port_open(HOST, PORT):
        # Server is already running in background; simply open the UI
        webbrowser.open(URL)
        return

    # Start lid & sleep monitor in background
    start_lid_monitor()

    # Schedule browser opening once server is listening
    browser_thread = threading.Thread(target=open_browser_when_ready, daemon=True)
    browser_thread.start()

    # Run Uvicorn directly inside this pythonw process (zero console, clean Proactor loop)
    import uvicorn
    uvicorn.run(
        "career_pulse.web.app:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
