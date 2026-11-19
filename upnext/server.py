"""Local API for the UI. Only listens on 127.0.0.1."""

import os
import platform
import subprocess
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import autopilot, config, credits, drive, jobs, library, names, subtitles, vlc

UI = Path(__file__).resolve().parent.parent / "ui"
app = FastAPI(title="Upnext")


@app.get("/api/ping")
def ping():
    return {"app": "upnext"}


@app.get("/api/state")
def state():
    """Polled about once a second by the UI."""
    return {"autopilot": autopilot.snapshot(), "jobs": jobs.listing(), "refreshing": library.refreshing()}


# --- library -----------------------------------------------------------------

@app.get("/api/library")
def get_library():
    return {"shows": library.as_json(), "sources": library.sources_summary(), "refreshing": library.refreshing()}


@app.post("/api/library/refresh")
def refresh():
    library.refresh(remote=True)
    return {"ok": True}


@app.post("/api/download")
def download(key: str = Body(...), season: int = Body(...), episode: int | None = Body(None)):
    from . import downloads
    if episode is None:
        return {"jobs": downloads.queue_season(key, season)}
    show = library.build().get(key)
    ep = show and show["seasons"].get(season, {}).get(episode)
    if not ep:
        raise HTTPException(404, "Episode not found")
    job = downloads.queue_episode(show["name"], ep)
    return {"jobs": [job.id] if job else []}


@app.post("/api/play")
def play(path: str = Body(..., embed=True)):
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    try:
        how = vlc.play(path)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"via": how}


@app.post("/api/reveal")
def reveal(path: str = Body(..., embed=True)):
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["open", "-R", path])
    elif system == "Windows":
        subprocess.run(["explorer", "/select,", path])
    else:
        subprocess.run(["xdg-open", str(Path(path).parent)])
    return {"ok": True}


@app.delete("/api/file")
def delete_file(path: str = Body(..., embed=True)):
    """Move a downloaded episode to the Trash (macOS) or delete it."""
    p = Path(path)
    if not p.exists() or not names.is_video(p):
        raise HTTPException(404, "File not found")
    if platform.system() == "Darwin":
        subprocess.run(["osascript", "-e", f'tell application "Finder" to delete POSIX file "{p}"'], capture_output=True)
    else:
        p.unlink()
    library.scan_local()
    return {"ok": True}


# --- autopilot ------------------------------------------------------------------

@app.post("/api/autopilot")
def set_autopilot(enabled: bool = Body(..., embed=True)):
    autopilot.state["enabled"] = enabled
    return autopilot.snapshot()


@app.post("/api/autopilot/next")
def play_next():
    if not autopilot.play_next_now():
        raise HTTPException(400, "The next episode isn't downloaded yet")
    return {"ok": True}


# --- subtitles ---------------------------------------------------------------------

@app.get("/api/videos")
def videos():
    """Every local episode, for the Subtitles page."""
    library.scan_local()
    out = []
    for show in library.as_json():
        for season in show["seasons"]:
            for ep in season["episodes"]:
                if ep["local"]:
                    out.append({"path": ep["local"]["path"], "series": show["name"], "code": ep["code"], "title": ep["title"]})
    return out


@app.get("/api/subtitles")
def subtitle_info(path: str):
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    return subtitles.describe(path)


@app.get("/api/ready")
def ready(path: str):
    """Asked by the Up Next card: is the next episode downloaded and are its subtitles done?"""
    return subtitles.readiness(path)


@app.get("/api/subtitles/search")
def subtitle_search(path: str):
    try:
        return {"results": subtitles.search(path)[:20], "has_key": True}
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"OpenSubtitles search failed: {e}")


@app.post("/api/subtitles/{action}")
def subtitle_action(action: str, body: dict = Body(...)):
    path = body.get("path", "")
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    if action == "auto":
        job = subtitles.queue_auto(path)
    elif action == "fetch":
        job = subtitles.queue_fetch(path, int(body["file_id"]), bool(body.get("hash_match")))
    elif action == "sync":
        srt_file = body.get("srt_file")
        if srt_file and (Path(srt_file).parent != Path(path).parent or not srt_file.endswith(".srt")):
            raise HTTPException(400, "Pick a subtitle file from the episode's folder")
        job = subtitles.queue_sync(path, body.get("stream_index"), srt_file)
    elif action == "shift":
        job = subtitles.queue_shift(path, float(body["seconds"]))
    elif action == "generate":
        job = subtitles.queue_generate(path)
    elif action == "embed":
        job = subtitles.queue_embed(path)
    else:
        raise HTTPException(404, "Unknown action")
    return {"job": job.id}


# --- jobs ------------------------------------------------------------------------------

@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: int):
    return {"ok": jobs.cancel(job_id)}


@app.post("/api/jobs/clear")
def clear():
    jobs.clear_finished()
    return {"ok": True}


# --- settings ----------------------------------------------------------------------------

@app.get("/api/settings")
def get_settings():
    s = config.load()
    # never send the key back to the page in full
    if s["opensubtitles_api_key"]:
        s = {**s, "opensubtitles_api_key": "••••" + s["opensubtitles_api_key"][-4:]}
    return {"settings": {k: v for k, v in s.items() if k != "vlc_password"},
            "drive": drive.status(),
            "tools": {"ffmpeg": bool(credits.ffmpeg()), "vlc": vlc.find_vlc()},
            "sources": library.sources_summary()}


@app.put("/api/settings")
def put_settings(changes: dict = Body(...)):
    changes.pop("vlc_password", None)
    if str(changes.get("opensubtitles_api_key", "")).startswith("••••"):
        changes.pop("opensubtitles_api_key")
    changes.pop("sources", None)
    s = config.save(changes)
    library.scan_local()
    return {k: v for k, v in s.items() if k != "vlc_password"}


@app.post("/api/sources")
def add_source(link: str = Body(...), name: str = Body("")):
    fid = drive.folder_id(link)
    if not fid:
        raise HTTPException(400, "That doesn't look like a Google Drive folder link")
    try:
        top = drive.folder_name(fid)
    except RuntimeError as e:
        raise HTTPException(400, f"Couldn't open that folder: {e}")
    sources = [s for s in config.load()["sources"] if s["folder_id"] != fid]
    sources.append({"folder_id": fid, "name": name.strip() or _guess_name(top) or f"Drive folder {fid[:6]}"})
    config.save({"sources": sources})
    library.refresh(remote=True)
    return {"sources": sources}


def _guess_name(folders):
    """'Game.of.Thrones.S04…', 'Game of Thrones Season 6…' -> 'Game of Thrones' (the words they share)."""
    if not folders:
        return None
    words = [names.series_key(f).split() for f in folders]
    shared = []
    for group in zip(*words):
        if len(set(group)) != 1 or group[0] in ("s", "season") or group[0][:1] == "s" and group[0][1:].isdigit():
            break
        shared.append(group[0])
    return names.pretty(" ".join(shared)) if shared else (folders[0] if len(folders) == 1 else None)


@app.delete("/api/sources/{fid}")
def remove_source(fid: str):
    config.save({"sources": [s for s in config.load()["sources"] if s["folder_id"] != fid]})
    library.refresh(remote=True)
    return {"ok": True}


@app.post("/api/drive/connect")
def drive_connect():
    if not drive.rclone_path():
        raise HTTPException(400, "rclone isn't installed")
    out = drive.connect()
    if out.returncode != 0:
        raise HTTPException(400, out.stderr.strip()[-300:] or "Sign-in failed")
    return drive.status()


# --- the UI --------------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(UI / "index.html")


app.mount("/", StaticFiles(directory=UI), name="ui")
