"""Start Upnext: the local server, the background workers and the app window.

python -m upnext            opens the app window
python -m upnext --browser  opens it in your web browser instead
"""

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import requests
import uvicorn

PORT = 8765
ROOT = Path(__file__).resolve().parent.parent


def _extend_path():
    # Apps started from Finder or the Dock get a bare PATH without Homebrew
    extra = ["/opt/homebrew/bin", "/usr/local/bin"]
    os.environ["PATH"] = os.pathsep.join([*extra, os.environ.get("PATH", "")])


def _already_running():
    try:
        return requests.get(f"http://127.0.0.1:{PORT}/api/ping", timeout=0.5).json().get("app") == "upnext"
    except (requests.RequestException, ValueError):
        return False


def _port_free():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) != 0


def serve():
    from . import autopilot, jobs, library
    from .server import app

    library.load_cache()
    library.refresh(remote=True)
    jobs.start()
    autopilot.start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def main():
    ap = argparse.ArgumentParser(prog="upnext")
    ap.add_argument("--browser", action="store_true", help="open in the web browser instead of an app window")
    ap.add_argument("--headless", action="store_true", help="just run the server and autopilot")
    args = ap.parse_args()
    _extend_path()
    url = f"http://127.0.0.1:{PORT}/"

    if not _already_running():
        if not _port_free():
            sys.exit(f"Port {PORT} is taken by another program")
        threading.Thread(target=serve, daemon=True).start()
        for _ in range(100):
            if _already_running():
                break
            time.sleep(0.1)

    if args.headless:
        print(f"Upnext is running at {url}  (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return
    if args.browser:
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return
    import webview
    _mac_identity()
    webview.create_window("Upnext", url, width=1240, height=820, min_size=(820, 560))
    webview.start()


def _mac_identity():
    """Show "Upnext" and its icon in the Dock and menu bar instead of "Python"."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle

        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        info["CFBundleName"] = "Upnext"
        icon = NSImage.alloc().initWithContentsOfFile_(str(ROOT / "assets" / "icon-1024.png"))
        if icon:
            NSApplication.sharedApplication().setApplicationIconImage_(icon)
    except Exception:
        pass  # cosmetic only


if __name__ == "__main__":
    main()
