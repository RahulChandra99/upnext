"""The library: every episode on Drive and on disk, grouped by series and season."""

import json
import os
import threading
import time
from pathlib import Path

from . import config, drive, names
from .config import DATA_DIR

CACHE = DATA_DIR / "drive_cache.json"
SKIP_DIRS = {".git", "node_modules"}
SKIP_SUFFIXES = (".fcpbundle", ".photoslibrary", ".imovielibrary", ".tvlibrary", ".app")

_lock = threading.Lock()
_remote = {}  # source folder_id -> {"name", "files": [{path, size}], "updated", "error"}
_local = {}  # path -> size
_refreshing = False


def load_cache():
    global _remote
    if CACHE.exists():
        try:
            _remote = json.loads(CACHE.read_text())
        except json.JSONDecodeError:
            _remote = {}


def refresh(remote=True, on_done=None):
    """Re-read Drive (slow, in the background) and the local folder (fast)."""
    global _refreshing
    scan_local()
    if not remote or _refreshing:
        return

    def work():
        global _refreshing
        _refreshing = True
        try:
            for src in config.load()["sources"]:
                fid = src["folder_id"]
                entry = {"name": src.get("name") or fid, "files": [], "updated": time.time(), "error": None}
                try:
                    entry["files"] = drive.list_files(fid)
                except Exception as e:  # keep the old listing if Drive is unreachable
                    entry = {**_remote.get(fid, entry), "error": str(e)}
                with _lock:
                    _remote[fid] = entry
            with _lock:
                known = {s["folder_id"] for s in config.load()["sources"]}
                for fid in list(_remote):
                    if fid not in known:
                        del _remote[fid]
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                CACHE.write_text(json.dumps(_remote))
        finally:
            _refreshing = False
            if on_done:
                on_done()

    threading.Thread(target=work, daemon=True).start()


def refreshing():
    return _refreshing


def scan_local(extra_dirs=()):
    """Find episode files under the download folder (3 levels deep is enough for Show/Season N/file)."""
    found = {}
    roots = [Path(config.load()["download_dir"]).expanduser(), *map(Path, extra_dirs)]
    for root in roots:
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).parts) - base_depth
            dirnames[:] = [d for d in dirnames
                           if depth < 3 and not d.startswith(".") and d not in SKIP_DIRS and not d.endswith(SKIP_SUFFIXES)]
            for f in filenames:
                if names.is_video(f) and not f.startswith("._") and names.parse(f):
                    p = os.path.join(dirpath, f)
                    try:
                        found[p] = os.path.getsize(p)
                    except OSError:
                        pass
    with _lock:
        _local.clear()
        _local.update(found)


def add_local(path):
    with _lock:
        try:
            _local[str(path)] = os.path.getsize(path)
        except OSError:
            pass


def build():
    """{series_key: {"name", "seasons": {season: {episode: ep}}}} where ep has remote and/or local."""
    shows = {}

    def slot(info):
        show = shows.setdefault(info["key"], {"key": info["key"], "name": info["series"], "seasons": {}})
        ep = show["seasons"].setdefault(info["season"], {}).setdefault(info["episode"], {
            "season": info["season"], "episode": info["episode"], "code": names.code(info["season"], info["episode"]),
            "title": "", "remote": None, "local": None,
        })
        if info["title"] and not ep["title"]:
            ep["title"] = info["title"]
        return ep

    with _lock:
        remote = {fid: dict(v) for fid, v in _remote.items()}
        local = dict(_local)
    for fid, src in remote.items():
        for f in src["files"]:
            if not names.is_video(f["path"]):
                continue
            info = names.parse(f["path"])
            if info:
                ep = slot(info)
                if not ep["remote"] or f["size"] > ep["remote"]["size"]:
                    ep["remote"] = {"source": fid, "path": f["path"], "size": f["size"]}
    for path, size in local.items():
        info = names.parse(path)
        if info:
            slot(info)["local"] = {"path": path, "size": size}
    return shows


def find(key, season, episode):
    show = build().get(key)
    return show and show["seasons"].get(season, {}).get(episode)


def next_episode(key, season, episode):
    """The episode after this one: next in the season, else the first of the next season."""
    show = build().get(key)
    if not show:
        return None
    order = sorted((s, e) for s, eps in show["seasons"].items() for e in eps)
    later = [se for se in order if se > (season, episode)]
    return show["seasons"][later[0][0]][later[0][1]] if later else None


def local_target(series_name, ep):
    """Where a download goes: <download folder>/<Series>/Season 06/<file name>."""
    root = Path(config.load()["download_dir"]).expanduser()
    return root / series_name / f"Season {ep['season']:02d}" / Path(ep["remote"]["path"]).name


def sources_summary():
    with _lock:
        return [{"folder_id": fid, "name": v.get("name"), "files": len(v.get("files", [])),
                 "updated": v.get("updated"), "error": v.get("error")} for fid, v in _remote.items()]


def as_json():
    shows = build()
    out = []
    for show in sorted(shows.values(), key=lambda s: s["name"].lower()):
        seasons = []
        for s in sorted(show["seasons"]):
            eps = [dict(show["seasons"][s][e]) for e in sorted(show["seasons"][s])]
            for ep in eps:
                ep["target"] = str(local_target(show["name"], ep)) if ep["remote"] and not ep["local"] else None
            seasons.append({"season": s, "episodes": eps,
                            "downloaded": sum(1 for e in eps if e["local"])})
        total = sum(len(x["episodes"]) for x in seasons)
        out.append({"key": show["key"], "name": show["name"], "seasons": seasons, "episodes": total,
                    "downloaded": sum(x["downloaded"] for x in seasons)})
    return out
