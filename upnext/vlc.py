"""Controlling VLC.

Upnext starts VLC itself with VLC's built-in web interface switched on, which
works the same on macOS, Windows and Linux. If you opened VLC yourself on a Mac,
it falls back to AppleScript so the autopilot still sees what's playing.
"""

import json
import os
import platform
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path

import requests

from . import config

MAC = platform.system() == "Darwin"
WINDOWS = platform.system() == "Windows"


def find_vlc():
    custom = config.load()["vlc_path"]
    candidates = [custom] if custom else []
    if MAC:
        candidates += ["/Applications/VLC.app/Contents/MacOS/VLC", str(Path.home() / "Applications/VLC.app/Contents/MacOS/VLC")]
    elif WINDOWS:
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(env):
                candidates.append(os.path.join(os.environ[env], "VideoLAN", "VLC", "vlc.exe"))
    candidates.append(shutil.which("vlc") or "")
    return next((c for c in candidates if c and os.path.exists(c)), None)


def _http(params=None, path="status.json"):
    s = config.load()
    r = requests.get(f"http://127.0.0.1:{s['vlc_port']}/requests/{path}", params=params,
                     auth=("", s["vlc_password"]), timeout=1.5)
    r.raise_for_status()
    return r.json()


def _http_up():
    try:
        _http()
        return True
    except (requests.RequestException, ValueError):
        return False


def _uri(path):
    return Path(path).resolve().as_uri()


def _path_from_uri(uri):
    if not uri or not uri.startswith("file:"):
        return ""
    return urllib.parse.unquote(urllib.parse.urlparse(uri).path) if not WINDOWS else \
        urllib.parse.unquote(uri[len("file:///"):]).replace("/", "\\")


def play(path, fullscreen=False):
    """Open a file in VLC, starting VLC if needed."""
    if _http_up():
        _http({"command": "in_play", "input": _uri(path)})
        if fullscreen:
            time.sleep(1.0)
            st = status()
            if st and not st["fullscreen"]:
                _http({"command": "fullscreen"})
        return "http"
    if MAC and _applescript_running():
        _applescript(f'open POSIX file {json.dumps(str(path))}' + ("\ndelay 1.5\nset fullscreen mode to true" if fullscreen else ""))
        return "applescript"
    exe = find_vlc()
    if not exe:
        raise RuntimeError("VLC isn't installed. Get it from videolan.org, or set its location in Settings.")
    s = config.load()
    args = [exe, "--extraintf=http", "--http-host=127.0.0.1", f"--http-port={s['vlc_port']}",
            f"--http-password={s['vlc_password']}", str(path)]
    if fullscreen:
        args.insert(1, "--fullscreen")
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=not WINDOWS)
    return "launched"


def status():
    """{name, path, time, length, playing, fullscreen, via} or None when nothing is loaded."""
    try:
        st = _http()
        if st.get("state") == "stopped" or not st.get("length"):
            return None
        path = ""
        try:
            pl = _http(path="playlist.json")
            path = _path_from_uri(_current_uri(pl))
        except (requests.RequestException, ValueError):
            pass
        meta = (st.get("information") or {}).get("category", {}).get("meta", {})
        return {
            "name": meta.get("filename") or meta.get("title") or Path(path).name,
            "path": path,
            "time": float(st.get("time", 0)),
            "length": float(st.get("length", 0)),
            "playing": st.get("state") == "playing",
            "fullscreen": bool(st.get("fullscreen")),
            "via": "http",
        }
    except (requests.RequestException, ValueError):
        pass
    if MAC:
        return _applescript_status()
    return None


def _current_uri(node):
    if isinstance(node, dict):
        if node.get("current") == "current" and node.get("uri"):
            return node["uri"]
        for child in node.get("children", []) or []:
            found = _current_uri(child)
            if found:
                return found
    return None


# --- macOS AppleScript fallback, for a VLC you opened yourself -------------

_AS_STATUS = """
if application "VLC" is running then
    tell application "VLC"
        try
            set p to path of current item
        on error
            set p to ""
        end try
        return (name of current item) & "\n" & p & "\n" & (current time) & "\n" & (duration of current item) & "\n" & playing & "\n" & fullscreen mode
    end tell
end if
return ""
"""


def _applescript(body):
    return subprocess.run(["osascript", "-e", f'tell application "VLC"\n{body}\nend tell'],
                          capture_output=True, text=True, timeout=10)


def _applescript_running():
    out = subprocess.run(["pgrep", "-x", "VLC"], capture_output=True)
    return out.returncode == 0


def _applescript_status():
    if not _applescript_running():
        return None
    out = subprocess.run(["osascript", "-e", _AS_STATUS], capture_output=True, text=True, timeout=10)
    lines = out.stdout.strip().split("\n")
    if out.returncode != 0 or len(lines) < 6:
        return None
    try:
        return {"name": lines[0], "path": lines[1], "time": float(lines[2]), "length": float(lines[3]),
                "playing": lines[4] == "true", "fullscreen": lines[5] == "true", "via": "applescript"}
    except ValueError:
        return None
