"""Finding where the end credits start.

Most shows end on credits that are white text over black. ffmpeg's blackdetect
counts a frame as black when 90% of it is dark, so credit text doesn't break
it up. The credits are the run of black stretches that lasts until the end.
"""

import json
import os
import re
import shutil
import subprocess
import threading

from .config import DATA_DIR

CACHE = DATA_DIR / "credits_cache.json"
_lock = threading.Lock()


def ffmpeg():
    return shutil.which("ffmpeg") or next(
        (p for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg") if os.path.exists(p)), None)


def ffprobe():
    return shutil.which("ffprobe") or next(
        (p for p in ("/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe") if os.path.exists(p)), None)


def detect(path, duration, scan=360, max_gap=5, min_len=30):
    """Seconds of end credits, or None if there's no clear credits block."""
    key = f"{path}|{os.path.getsize(path) if os.path.exists(path) else 0}"
    cache = _load()
    if key in cache:
        return cache[key]
    start = max(0, duration - scan)
    try:
        out = subprocess.run(
            [ffmpeg(), "-hide_banner", "-nostats", "-ss", str(start), "-i", path, "-an", "-sn",
             "-vf", "scale=320:-2,blackdetect=d=1:pix_th=0.10:pic_th=0.90", "-f", "null", "-"],
            capture_output=True, text=True, timeout=240)
    except (OSError, TypeError, subprocess.TimeoutExpired):
        return None
    spans = [(start + float(a), start + float(b))
             for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", out.stderr)]
    result = credits_length(spans, duration, max_gap, min_len)
    cache[key] = result
    _save(cache)
    return result


def credits_length(spans, duration, max_gap=5, min_len=30):
    """Given black stretches [(start, end)] in seconds, how long the end credits run."""
    if not spans or duration - spans[-1][1] > max_gap:
        return None
    credits_start = spans[-1][0]
    for a, b in reversed(spans[:-1]):
        if credits_start - b > max_gap:
            break
        credits_start = a
    length = duration - credits_start
    return length if length >= min_len else None


def _load():
    with _lock:
        try:
            return json.loads(CACHE.read_text())
        except (OSError, json.JSONDecodeError):
            return {}


def _save(cache):
    with _lock:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
