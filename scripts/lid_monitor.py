"""
CareerPulse Laptop Lid & Sleep Monitor.
Listens for Windows power broadcast events to pause/resume scheduler on sleep/wake.
Stdlib only (ctypes, urllib.request, time).
"""

import ctypes
from ctypes import wintypes
import time
import urllib.request

WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMEAUTOMATIC = 0x0012

# Win32 Types & Structures
LRESULT = ctypes.c_longlong
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT

user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID
]
user32.CreateWindowExW.restype = wintypes.HWND

user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


def post_api(url: str):
    try:
        req = urllib.request.Request(url, data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            pass
    except Exception:
        pass


def wait_for_server():
    for _ in range(30):
        try:
            req = urllib.request.Request("http://127.0.0.1:8000/api/scheduler/status")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_POWERBROADCAST:
        if wparam == PBT_APMSUSPEND:
            post_api("http://127.0.0.1:8000/api/scheduler/pause")
        elif wparam == PBT_APMRESUMEAUTOMATIC:
            time.sleep(2)
            post_api("http://127.0.0.1:8000/api/scheduler/resume")
        return 1

    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def main():
    # Ensure single instance via Win32 Named Mutex
    ERROR_ALREADY_EXISTS = 183
    mutex = kernel32.CreateMutexW(None, False, "CareerPulseLidMonitorMutex")
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return

    # Wait up to 30s until local CareerPulse server is responding
    wait_for_server()

    # Retain reference to callback function to avoid garbage collection
    proc_callback = WNDPROC(wnd_proc)

    h_instance = kernel32.GetModuleHandleW(None)
    class_name = "CareerPulseLidMonitorClass"

    wc = WNDCLASSW()
    wc.lpfnWndProc = proc_callback
    wc.lpszClassName = class_name
    wc.hInstance = h_instance

    user32.RegisterClassW(ctypes.byref(wc))

    # Create message-only window
    HWND_MESSAGE = wintypes.HWND(-3)
    hwnd = user32.CreateWindowExW(
        0, class_name, "CareerPulseLidMonitor",
        0, 0, 0, 0, 0,
        HWND_MESSAGE, None, h_instance, None
    )

    if not hwnd:
        return

    # Standard Win32 Message Pump
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


if __name__ == "__main__":
    main()
