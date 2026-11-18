"""Turning messy release file names into (series, season, episode, title)."""

import re
from pathlib import Path

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".webm", ".ts", ".wmv"}

# S06E05, s6e5, S06 E05, 6x05
EPISODE_RE = re.compile(r"(?<![a-z0-9])S(\d{1,2})[\s._-]*E(\d{1,3})|(?<![a-z0-9])(\d{1,2})x(\d{2,3})(?![0-9])", re.IGNORECASE)
# Where the episode title stops and release junk starts
JUNK_RE = re.compile(
    r"^(\d{3,4}p|web|webrip|web-?dl|bluray|brrip|hdtv|x26\d|h26\d|hevc|aac|ac3|dts|ddp?\d|"
    r"repack|proper|internal|10bit|hdr|amzn|nf|hmax|dsnp|5\.1ch|\d\.\d)$",
    re.IGNORECASE,
)
SMALL_WORDS = {"of", "the", "and", "a", "an", "in", "on", "at", "to", "for", "or"}


def is_video(path):
    return Path(path).suffix.lower() in VIDEO_EXTS


def parse(filename):
    """Return dict(series, key, season, episode, title) or None if it isn't an episode."""
    stem = Path(filename).stem
    m = EPISODE_RE.search(stem)
    if not m:
        return None
    season = int(m.group(1) or m.group(3))
    episode = int(m.group(2) or m.group(4))
    series = _clean(stem[: m.start()])
    if not series:
        # "Show Name/Season 1/S01E01.mkv": use the nearest folder that isn't just a season number
        for parent in Path(filename).parents:
            series = _clean(re.sub(r"(?i)\b(s|season)\s*\d+\b.*$", "", parent.name))
            if series:
                break
    return {
        "series": pretty(series) if series else "Unknown",
        "key": series_key(series or "Unknown"),
        "season": season,
        "episode": episode,
        "title": episode_title(stem[m.end():]),
    }


def episode_title(rest):
    words = []
    for w in re.split(r"[. _]+", rest):
        w = w.strip("-[]()")
        if not w:
            continue
        if JUNK_RE.match(w):
            break
        words.append(w)
    return " ".join(words)


def series_key(name):
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def pretty(name):
    words = name.split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if i and lw in SMALL_WORDS:
            out.append(lw)
        elif w.isupper() and len(w) <= 3 and lw not in SMALL_WORDS:
            out.append(w)  # US, UK, SVU
        elif w.isupper() or w.islower():
            out.append(w[:1].upper() + w[1:].lower())
        else:
            out.append(w)
    return " ".join(out)


def code(season, episode):
    return f"S{season:02d}E{episode:02d}"


def _clean(text):
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"[\[\(].*?[\]\)]", " ", text)
    text = re.sub(r"\b(19|20)\d{2}\b\s*$", "", text.strip())
    return re.sub(r"\s+", " ", text).strip(" -")
