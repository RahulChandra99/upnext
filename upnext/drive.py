"""Google Drive access through rclone."""

import json
import re
import shutil
import subprocess

from . import config


def rclone_path():
    return shutil.which("rclone") or next(
        (p for p in ("/opt/homebrew/bin/rclone", "/usr/local/bin/rclone") if shutil.which(p)), None)


def status():
    """What the Settings page needs to know about the Drive connection."""
    exe = rclone_path()
    if not exe:
        return {"installed": False, "connected": False}
    remote = config.load()["rclone_remote"]
    out = subprocess.run([exe, "listremotes"], capture_output=True, text=True)
    return {"installed": True, "connected": f"{remote}:" in out.stdout.split()}


def connect():
    """Create the read-only Drive remote. rclone opens the browser for the Google sign-in."""
    exe = rclone_path()
    remote = config.load()["rclone_remote"]
    return subprocess.run([exe, "config", "create", remote, "drive", "scope=drive.readonly"],
                          capture_output=True, text=True, timeout=600)


def folder_id(link_or_id):
    """Accept a Drive folder link or a bare folder ID."""
    m = re.search(r"folders/([A-Za-z0-9_-]{10,})", link_or_id) or re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", link_or_id)
    if m:
        return m.group(1)
    link_or_id = link_or_id.strip()
    return link_or_id if re.fullmatch(r"[A-Za-z0-9_-]{10,}", link_or_id) else None


def _base(fid):
    s = config.load()
    return [rclone_path(), f"--drive-root-folder-id={fid}"], f"{s['rclone_remote']}:"


def list_files(fid, recursive=True):
    """Every file under a Drive folder: [{path, size}]."""
    base, remote = _base(fid)
    args = base + ["lsjson", "--files-only", "--fast-list", remote]
    if recursive:
        args.insert(-1, "-R")
    out = subprocess.run(args, capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "rclone failed")
    return [{"path": f["Path"], "size": f["Size"]} for f in json.loads(out.stdout)]


def folder_name(fid):
    """Best guess at a readable name for a source: its single top-level folder, if any."""
    base, remote = _base(fid)
    out = subprocess.run(base + ["lsjson", "--dirs-only", remote], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "rclone failed")
    return [d["Path"] for d in json.loads(out.stdout)]


def download_cmd(fid, remote_path, dest):
    base, remote = _base(fid)
    # 16 parallel streams: about 4x faster than one stream from Drive (measured 2.6 vs 10 MiB/s)
    return base + ["copyto", remote + remote_path, str(dest),
                   "--multi-thread-streams=16", "--multi-thread-cutoff=1M",
                   "--use-json-log", "--stats=1s", "--stats-log-level=NOTICE", "-v"]
