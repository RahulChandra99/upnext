"""Lining subtitles up with what's actually said.

Whisper gives a word-by-word transcript with timings. Wherever a subtitle line
starts with the same four words as a run of spoken words, and those four words
appear in no other line, that's an anchor: this line belongs at that moment.
From a few hundred anchors we fit how subtitle time maps to video time.

Usually that's a straight line: a constant offset, sometimes with a slight
speed difference (25 vs 23.976 fps releases). When a release has a cut the
subtitles don't (a recap removed, an ad break), the offset jumps partway, and a
straight line fits badly. Then the offset is followed piece by piece instead.

On S07E04 a straight line fit 228 anchors to within 0.14s (median), where
ffsubsync had returned -60s for a file that was 84s late.
"""

import re
from collections import defaultdict

import numpy as np

AD_RE = re.compile(r"www\.|https?://|\.(com|net|org)\b|opensubtitles|subtitles by|synced by|subscene", re.IGNORECASE)
RUN = 4


def words_of(text):
    text = re.sub(r"<[^>]+>|\{[^}]*\}|\[[^\]]*\]|\([^)]*\)", " ", text.lower())
    text = text.replace("’", "'")
    return re.sub(r"[^a-z0-9' ]", " ", text).split()


def is_ad(text):
    return bool(AD_RE.search(text))


def anchors(spoken, lines):
    """spoken: [{"start", "word"}] from Whisper. lines: [(start_seconds, text)].
    Returns [(subtitle_time, video_time)] for lines whose opening words were heard."""
    index = defaultdict(list)
    for i, (_, text) in enumerate(lines):
        w = words_of(text)
        if len(w) >= RUN:
            index[tuple(w[:RUN])].append(i)
    flat = [(x, w["start"]) for w in spoken for x in words_of(w["word"])]
    used, points = set(), []
    for k in range(len(flat) - RUN + 1):
        hits = index.get(tuple(x for x, _ in flat[k:k + RUN]))
        if hits and len(hits) == 1 and hits[0] not in used:
            used.add(hits[0])
            points.append((lines[hits[0]][0], flat[k][1]))
    return sorted(points)


def fit(points):
    """Best mapping from subtitle time to video time. Returns a dict with a
    `map(t)` function and how well it fits, or None with fewer than 15 anchors."""
    if len(points) < 15:
        return None
    pts = np.array(points, dtype=float)
    x, y = pts[:, 0], pts[:, 1]

    # straight line, refit twice without the outliers (wrong matches, repeated phrases)
    keep = np.ones(len(x), bool)
    for _ in range(3):
        b, a = np.polyfit(x[keep], y[keep], 1)
        res = np.abs(y - (a + b * x))
        keep = res < max(0.6, 3 * np.median(res[keep]))
    line = _summary("linear", lambda t: a + b * np.asarray(t, float), x[keep], y[keep], len(points))
    line.update(offset=float(a + b * np.median(x) - np.median(x)), speed=float(b))
    if line["p90"] <= 1.0:
        return line

    # piecewise: smoothed per-anchor offsets, interpolated between anchors
    off = y - x
    k = 9
    smooth = np.array([np.median(off[max(0, i - k // 2): i + k // 2 + 1]) for i in range(len(off))])
    good = np.abs(off - smooth) < 1.0
    xs, os_ = x[good], smooth[good]
    piece = _summary("piecewise", lambda t: np.asarray(t, float) + np.interp(t, xs, os_), x[good], y[good], len(points))
    piece.update(offset=float(np.median(os_)), speed=1.0)
    return piece if piece["p90"] < line["p90"] else line


def _summary(kind, fn, x, y, total):
    res = np.abs(y - fn(x))
    return {"kind": kind, "map": fn, "anchors": int(len(x)), "found": total,
            "median": float(np.median(res)), "p90": float(np.percentile(res, 90))}
