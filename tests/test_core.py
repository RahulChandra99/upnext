"""Run with: .venv/bin/python -m pytest -q   (or .venv/bin/python tests/test_core.py)"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import srt  # noqa: E402

from upnext import credits, names, subtitles  # noqa: E402


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


if __name__ == "__main__":
    import tempfile
    test_names(); test_credits_length(); test_wrap(); test_lines_from_words()
    with tempfile.TemporaryDirectory() as d:
        test_shift(Path(d))
    print("all passed")
