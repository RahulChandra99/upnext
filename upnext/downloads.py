"""Downloading episodes from Drive as background jobs."""

import json
import subprocess
from pathlib import Path

from . import config, drive, jobs, library, names


def queue_episode(series_name, ep, then_subtitles=None, urgent=False):
    """Queue a download for one library episode. Returns the job, or None if it's already on disk."""
    if ep.get("local") or not ep.get("remote"):
        return None
    dest = library.local_target(series_name, ep)
    title = f"{series_name} {ep['code']}" + (f" · {ep['title']}" if ep["title"] else "")
    if then_subtitles is None:
        then_subtitles = config.load()["auto_subtitles"]

    def run(job):
        download(job, ep["remote"], dest)
        library.add_local(dest)
        if then_subtitles:
            from . import subtitles
            subtitles.queue_auto(str(dest), urgent=urgent)
        return {"path": str(dest)}

    return jobs.submit("download", "download", title, run, key=f"download:{dest}", urgent=urgent)


def download(job, remote, dest):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size == remote["size"]:
        job.update(1, "Already downloaded")
        return
    total = remote["size"]
    job.update(0, f"Downloading {total / 1e9:.2f} GB")
    proc = subprocess.Popen(drive.download_cmd(remote["source"], remote["path"], dest),
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    job.proc = proc
    last_error = ""
    for line in proc.stderr:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        stats = entry.get("stats")
        if stats and stats.get("totalBytes"):
            done = stats.get("bytes", 0)
            speed = stats.get("speed", 0) / (1024 * 1024)
            eta = stats.get("eta")
            msg = f"{done / 1e6:,.0f} of {total / 1e6:,.0f} MB · {speed:.1f} MB/s"
            if eta:
                msg += f" · {int(eta) // 60}:{int(eta) % 60:02d} left"
            job.update(done / stats["totalBytes"], msg)
        elif entry.get("level") == "error":
            last_error = entry.get("msg", "")
    proc.wait()
    job.proc = None
    if job.cancel_requested:
        raise jobs.Cancelled()
    if proc.returncode != 0:
        raise RuntimeError(last_error or f"rclone exited with code {proc.returncode}")
    job.update(1, "Downloaded")


def queue_season(key, season):
    show = library.build().get(key)
    if not show:
        return []
    queued = []
    for e in sorted(show["seasons"].get(season, {})):
        job = queue_episode(show["name"], show["seasons"][season][e])
        if job:
            queued.append(job.id)
    return queued


def label(series_name, ep):
    return f"{series_name} {names.code(ep['season'], ep['episode'])}"
