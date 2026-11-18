"""Settings, stored as JSON in the OS's app-data folder (not in the repo)."""

import json
import os
import secrets
import threading
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

CONFIG_DIR = Path(user_config_dir("Upnext", appauthor=False))
DATA_DIR = Path(user_data_dir("Upnext", appauthor=False))
CONFIG_FILE = CONFIG_DIR / "settings.json"

DEFAULTS = {
    "rclone_remote": "gdrive",
    # Drive folders to read shows from: [{"name": "...", "folder_id": "..."}]
    "sources": [],
    "download_dir": str(Path.home() / "Movies" / "Upnext"),
    "prefetch_minutes": 15,
    "countdown_seconds": 15,
    "autoplay": True,
    "detect_credits": True,
    "auto_subtitles": True,
    "generate_if_not_found": True,
    "embed_subtitles": True,
    "opensubtitles_api_key": "",
    # small: about 5 min per 50 min episode on an M4 GPU (turbo ~10, base ~2), same lines on a test clip
    "whisper_model": "small",
    "vlc_path": "",
    "vlc_port": 8089,
    "vlc_password": "",
}

_lock = threading.Lock()


def _read():
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def load():
    """Defaults plus whatever you've changed. Only the changes are stored, so a
    better default in a later version still reaches you."""
    with _lock:
        data = _read()
        if not data.get("vlc_password"):
            data["vlc_password"] = secrets.token_urlsafe(12)
            _write(data)
        return {**DEFAULTS, **data}


def save(changes):
    with _lock:
        data = _read()
        for k, v in changes.items():
            if k not in DEFAULTS:
                continue
            if v == DEFAULTS[k]:
                data.pop(k, None)
            else:
                data[k] = v
        _write(data)
    return load()


def _write(data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, CONFIG_FILE)
