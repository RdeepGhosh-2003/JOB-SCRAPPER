"""
CareerPulse Dashboard Desktop Launcher.
100% Pure Python - Zero PowerShell, Zero VBScript, Zero Antivirus False Positives.

When launched:
- If server is already running on port 8000: opens browser to http://127.0.0.1:8000 and exits.
- If server is not running: opens browser after 1.5s and runs the FastAPI server silently via pythonw.
"""

import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def is_port_open(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def open_browser_when_ready():
    # Wait up to 10 seconds for server to be ready, then open browser
    for _ in range(20):
        time.sleep(0.5)
        if is_port_open(HOST, PORT):
            break
    webbrowser.open(URL)


def main():
    if is_port_open(HOST, PORT):
        # Server is already active, simply open the page
        webbrowser.open(URL)
        return

    # Add project root to sys.path
    project_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(project_dir))

    # Schedule browser opening in a background thread once port 8000 binds
    browser_thread = threading.Thread(target=open_browser_when_ready, daemon=True)
    browser_thread.start()

    # Run the server directly inside this pythonw process
    import uvicorn
    uvicorn.run("career_pulse.web.app:app", host=HOST, port=PORT, reload=False, log_config=None)


if __name__ == "__main__":
    main()
