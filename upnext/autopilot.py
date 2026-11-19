"""Watches VLC: prefetches the next episode, finds the credits, shows Up Next, plays it."""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

from . import config, credits, downloads, library, names, vlc

state = {
    "now": None,  # what VLC is playing, plus parsed episode info
    "next": None,  # the episode after it
    "credits_at": None,  # seconds before the end where the credits start
    "upnext": None,  # {"label", "seconds", "started"} while the countdown card is up
    "enabled": True,
    "message": "",
}
_credits = {}  # path -> seconds of credits (None while unknown)
_prompted = set()  # paths we've already shown the countdown for
_prefetched = set()
_subs_checked = set()  # next-episode paths we've made sure have subtitles coming


def snapshot():
    return dict(state)


def _ep_label(series, ep):
    return f"{names.code(ep['season'], ep['episode'])}" + (f" · {ep['title']}" if ep.get("title") else "")


def tick():
    st = vlc.status()
    if not st or not st["length"]:
        state.update(now=None, next=None, credits_at=None)
        return 5
    info = names.parse(st["path"] or st["name"]) or names.parse(st["name"])
    remaining = st["length"] - st["time"]
    state["now"] = {**st, "remaining": remaining, "info": info}
    if not info:
        state.update(next=None, credits_at=None)
        return 5

    if st["path"]:
        library.add_local(st["path"])
    nxt = library.next_episode(info["key"], info["season"], info["episode"])
    show = library.build().get(info["key"])
    series_name = show["name"] if show else info["series"]
    state["next"] = nxt and {**nxt, "series": series_name, "label": _ep_label(series_name, nxt),
                             "target": str(_target(series_name, nxt)[0]) if nxt["remote"] or nxt["local"] else None}
    s = config.load()
    if not state["enabled"] or not nxt:
        return 5

    # 1. prefetch
    if not nxt["local"] and nxt["remote"] and remaining <= s["prefetch_minutes"] * 60 and nxt["code"] + info["key"] not in _prefetched:
        _prefetched.add(nxt["code"] + info["key"])
        # urgent: ahead of a season download, and its subtitles go first in their queue too
        downloads.queue_episode(series_name, nxt, then_subtitles=s["auto_subtitles"], urgent=True)

    # 1b. next episode already on disk: get its subtitles ready now, not at the credits
    if nxt["local"] and s["auto_subtitles"] and nxt["local"]["path"] not in _subs_checked:
        _subs_checked.add(nxt["local"]["path"])
        threading.Thread(target=_prepare_subtitles, args=(nxt["local"]["path"],), daemon=True).start()

    # 2. credits, worked out once per file in the background
    path = st["path"]
    if s["detect_credits"] and path and os.path.exists(path) and path not in _credits:
        _credits[path] = None

        def find():
            _credits[path] = credits.detect(path, st["length"])

        threading.Thread(target=find, daemon=True).start()
    state["credits_at"] = _credits.get(path)

    # 3. Up Next
    if not s["autoplay"] or (path or st["name"]) in _prompted:
        return 5
    show_at = state["credits_at"] or s["countdown_seconds"]
    if remaining <= show_at:
        _prompted.add(path or st["name"])
        threading.Thread(target=_up_next, args=(series_name, nxt, st["fullscreen"]), daemon=True).start()
        return 2
    return 1 if remaining <= show_at + 15 else 5


def _target(series_name, ep):
    if ep["local"]:
        return Path(ep["local"]["path"]), ep["local"]["size"]
    return library.local_target(series_name, ep), ep["remote"]["size"]


def _prepare_subtitles(video):
    """Queue its subtitles at the front, or move an already queued job there."""
    from . import jobs, subtitles
    if jobs.active(f"subs:{video}") or subtitles.needs_subtitles(video):
        subtitles.queue_auto(video, urgent=True)


def _up_next(series_name, ep, fullscreen):
    path, size = _target(series_name, ep)
    label = _ep_label(series_name, ep)
    seconds = config.load()["countdown_seconds"]
    state["upnext"] = {"label": label, "series": series_name, "seconds": seconds, "started": time.time()}
    try:
        popup = subprocess.run([sys.executable, "-m", "upnext.popup", "--title", label, "--show", series_name,
                                "--seconds", str(seconds), "--wait-file", str(path), "--size", str(size)]
                               + (["--ready-url", f"http://127.0.0.1:{config.PORT}/api/ready?" + urlencode({"path": str(path)})]
                                  if config.load()["auto_subtitles"] else []),
                               cwd=str(Path(__file__).resolve().parent.parent))
        if popup.returncode == 0:
            vlc.play(path, fullscreen)
            state["message"] = f"Playing {series_name} {label}"
        else:
            state["message"] = "Autoplay cancelled"
    finally:
        state["upnext"] = None


def play_next_now():
    nxt = state.get("next")
    now = state.get("now")
    if not nxt or not now:
        return False
    path, _ = _target(nxt["series"], nxt)
    if not path.exists():
        return False
    _prompted.add(now["path"] or now["name"])
    vlc.play(path, now.get("fullscreen", False))
    return True


def run_forever():
    while True:
        try:
            delay = tick()
        except Exception as e:  # never let a hiccup kill the watcher
            state["message"] = f"Watcher error: {e}"
            delay = 5
        time.sleep(delay)


def start():
    threading.Thread(target=run_forever, daemon=True).start()
