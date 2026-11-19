"""Run with: .venv/bin/python -m pytest -q   (or .venv/bin/python tests/test_core.py)"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import srt  # noqa: E402

from upnext import align, credits, jobs, names, subtitles  # noqa: E402


def test_names():
    cases = {
        "Game.of.Thrones.S06E05.The.Door.1080p.WEB-DL.SUJAIDR.mkv": ("Game of Thrones", 6, 5, "The Door"),
        "Game Of Thrones S07E01.mp4": ("Game of Thrones", 7, 1, ""),
        "GAME.OF.THRONES.S01E01.mkv": ("Game of Thrones", 1, 1, ""),
        "Severance/Season 2/S02E01.mkv": ("Severance", 2, 1, ""),
        "The.Office.US.S02E01.The.Dundies.720p.WEB.mkv": ("The Office US", 2, 1, "The Dundies"),
        "breaking_bad_3x07_one_minute.mkv": ("Breaking Bad", 3, 7, "one minute"),
        "Severance (2022) - S01E03 - In Perpetuity [1080p].mkv": ("Severance", 1, 3, "In Perpetuity"),
    }
    for name, (series, s, e, title) in cases.items():
        got = names.parse(name)
        assert (got["series"], got["season"], got["episode"], got["title"]) == (series, s, e, title), (name, got)
    assert names.parse("holiday.mp4") is None
    assert names.parse("show.1080x720.mkv") is None
    assert names.parse("Game.of.Thrones.S01E01.mkv")["key"] == names.parse("Game Of Thrones S01E02.mkv")["key"]


def test_credits_length():
    # S06E05 measured: last scene cuts to black at 55:25.8, credits run to the end with short gaps
    spans = [(3325.8, 3365.3), (3365.9, 3367.9), (3368.6, 3372.2), (3372.6, 3375.3), (3377.3, 3380.6),
             (3381.9, 3386.7), (3389.5, 3390.9), (3391.6, 3393.0), (3394.5, 3402.5), (3405.1, 3406.5)]
    assert round(credits.credits_length(spans, 3406.6)) == 81
    # a dark scene earlier on, then a gap, doesn't count as credits
    assert credits.credits_length([(3000, 3010), (3380, 3406)], 3406.6) is None
    # black stretch that ends well before the file does isn't credits
    assert credits.credits_length([(3300, 3360)], 3406.6) is None


def test_shift(tmp_path):
    src = tmp_path / "a.srt"
    src.write_text(srt.compose([srt.Subtitle(1, datetime.timedelta(seconds=1), datetime.timedelta(seconds=3), "Hold the door")]))
    subtitles.shift(src, src, -1.5)
    sub = list(srt.parse(src.read_text()))[0]
    assert sub.start == datetime.timedelta(0) and sub.end == datetime.timedelta(seconds=1.5)


def test_wrap():
    assert subtitles._wrap("Short line") == "Short line"
    two = subtitles._wrap("You know nothing, Jon Snow, and you never will, not while I live")
    assert two.count("\n") == 1 and all(len(l) <= 42 for l in two.split("\n"))


def test_lines_from_words():
    w = lambda s, e, t: {"start": s, "end": e, "word": t}
    words = [w(0.0, 0.3, " Hold"), w(0.3, 0.5, " the"), w(0.5, 0.9, " door,"), w(0.9, 1.2, " Hodor!"),
             w(3.0, 3.4, " What"), w(3.4, 3.6, " happened?")]
    lines = subtitles.lines_from_words(words)
    assert [t.strip() for _, _, t in lines] == ["Hold the door, Hodor!", "What happened?"]
    assert lines[1][0] == 3.0


def _episode(n=200, seed=1):
    """Fake subtitle lines with distinct wording, one every ~12s."""
    import random
    rng = random.Random(seed)
    vocab = ["winter", "dragon", "throne", "north", "crow", "wall", "king", "queen", "gold", "sword",
             "fire", "blood", "ship", "lord", "lady", "night", "wolf", "lion", "debt", "dagger", "hand", "maester"]
    return [(10 + i * 12.0, " ".join(rng.choice(vocab) for _ in range(6))) for i in range(n)]


def _speak(lines, mapping):
    """What Whisper would hear: each line's words at mapping(line start), 0.3s apart."""
    out = []
    for t, text in lines:
        v = mapping(t)
        if v is None:
            continue
        for j, w in enumerate(text.split()):
            out.append({"start": v + 0.3 * j, "end": v + 0.3 * j + 0.25, "word": " " + w})
    return out


def test_align_constant_offset():
    lines = _episode()
    r = align.fit(align.anchors(_speak(lines, lambda t: t - 83.85), lines))
    assert r["kind"] == "linear" and abs(r["offset"] + 83.85) < 0.05 and r["median"] < 0.05


def test_align_speed():
    lines = _episode()
    r = align.fit(align.anchors(_speak(lines, lambda t: t * 1.042709 + 2.0), lines))  # 25 vs 23.976 fps
    assert r["kind"] == "linear" and abs(r["speed"] - 1.042709) < 0.001 and r["p90"] < 0.1


def test_align_cut():
    lines = _episode()
    # a 40s scene missing from the video at the 20 minute mark: later lines are 40s earlier
    r = align.fit(align.anchors(_speak(lines, lambda t: t if t < 1200 else (None if t < 1240 else t - 40)), lines))
    assert r["kind"] == "piecewise"
    assert abs(float(r["map"](600)) - 600) < 0.5 and abs(float(r["map"](2000)) - 1960) < 0.5


def test_align_wrong_episode():
    assert align.fit(align.anchors(_speak(_episode(seed=2), lambda t: t), _episode(seed=1))) is None


def test_ads():
    assert align.is_ad('<font color="#ffff00">www.tvsubtitles.net</font>')
    assert align.is_ad("Subtitles by explosiveskull")
    assert not align.is_ad("Bad things are coming.")


def test_urgent_jobs_first():
    # a season's subtitles are queued, then the episode you're about to watch jumps ahead
    a = jobs.submit("subtitles", "t", "E05", lambda j: None, key="t:5")
    b = jobs.submit("subtitles", "t", "E06", lambda j: None, key="t:6")
    jobs.submit("subtitles", "t", "E06", lambda j: None, key="t:6", urgent=True)  # bump b
    c = jobs.submit("subtitles", "t", "E07", lambda j: None, key="t:7", urgent=True)
    q = jobs._queues["subtitles"]
    order = [q.get()[2] for _ in range(q.qsize())]
    assert order == [b, c, a, b]  # the stale entry for b comes last and the worker skips it
    for j in (a, b, c):
        jobs.cancel(j.id)


if __name__ == "__main__":
    import tempfile
    test_names(); test_credits_length(); test_wrap(); test_lines_from_words(); test_urgent_jobs_first()
    test_align_constant_offset(); test_align_speed(); test_align_cut(); test_align_wrong_episode(); test_ads()
    with tempfile.TemporaryDirectory() as d:
        test_shift(Path(d))
    print("all passed")
