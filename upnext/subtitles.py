"""English subtitles: find online, sync to the audio, shift by hand, generate, embed.

The automatic pipeline for a video:
  1. It already has an English text track inside: nothing to do.
  2. There's a .srt next to it: sync that to the audio.
  3. Otherwise search OpenSubtitles. A file-hash match is made for this exact
     release and is used as is; anything else gets synced to the audio.
  4. Nothing found (or no API key): transcribe the audio with Whisper.
  5. Embed the result as a default English track (MKV and MP4), keeping the .srt too.
"""

import datetime
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import requests
import srt

from . import config, jobs, names
from .credits import ffmpeg, ffprobe

OS_API = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "Upnext v0.1"
OUR_TITLE = "English (Upnext)"
TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
EMBEDDABLE = {".mkv": "srt", ".mp4": "mov_text", ".m4v": "mov_text", ".mov": "mov_text"}


# --- what's already there ---------------------------------------------------

def streams(video):
    out = subprocess.run([ffprobe(), "-v", "error", "-show_entries",
                          "stream=index,codec_type,codec_name:stream_tags=language,title:format=duration",
                          "-of", "json", str(video)], capture_output=True, text=True)
    data = json.loads(out.stdout or "{}")
    found = data.get("streams", [])
    for s in found:
        # MKV tags come back as LANGUAGE or language depending on the muxer
        s["tags"] = {k.lower(): v for k, v in (s.get("tags") or {}).items()}
    return found, float(data.get("format", {}).get("duration") or 0)


def english_tracks(video):
    subs = [s for s in streams(video)[0] if s.get("codec_type") == "subtitle"]
    return [s for s in subs if (s.get("tags", {}).get("language") or "").lower() in ("eng", "en", "english")]


def sidecar(video):
    """The subtitle file Upnext writes, and VLC picks up automatically: Show.S01E01.en.srt"""
    return Path(video).with_suffix(".en.srt")


def existing_sidecar(video):
    v = Path(video)
    for cand in (v.with_suffix(".en.srt"), v.with_suffix(".eng.srt"), v.with_suffix(".srt"), v.with_suffix(".English.srt")):
        if cand.exists():
            return cand
    return None


def describe(video):
    """Subtitle state for the UI."""
    eng = english_tracks(video)
    side = existing_sidecar(video)
    return {
        "embedded": [{"index": s["index"], "codec": s.get("codec_name"), "title": s.get("tags", {}).get("title", ""),
                      "ours": s.get("tags", {}).get("title") == OUR_TITLE} for s in eng],
        "sidecar": str(side) if side else None,
        "can_embed": Path(video).suffix.lower() in EMBEDDABLE,
    }


# --- OpenSubtitles ------------------------------------------------------------

def file_hash(path):
    """OpenSubtitles' movie hash: file size plus the 64-bit sums of the first and last 64 KB."""
    size = os.path.getsize(path)
    if size < 131072:
        return None
    h = size
    with open(path, "rb") as f:
        for offset in (0, size - 65536):
            f.seek(offset)
            chunk = f.read(65536)
            h += sum(struct.unpack("<8192Q", chunk))
    return f"{h & 0xFFFFFFFFFFFFFFFF:016x}"


def _headers(with_key=True):
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    key = config.load()["opensubtitles_api_key"].strip()
    if with_key and key:
        h["Api-Key"] = key
    return h


def search(video):
    """English subtitles for this video, best first."""
    if not config.load()["opensubtitles_api_key"].strip():
        raise RuntimeError("OpenSubtitles needs a free API key for searching. Add one in Settings")
    info = names.parse(Path(video).name) or {}
    params = {"languages": "en"}
    try:
        params["moviehash"] = file_hash(video)
    except OSError:
        pass
    if info:
        params.update(query=info["series"].lower(), season_number=info["season"], episode_number=info["episode"])
    else:
        params["query"] = re.sub(r"[._]+", " ", Path(video).stem).lower()
    r = requests.get(f"{OS_API}/subtitles", params=dict(sorted(params.items())), headers=_headers(), timeout=20)
    if r.status_code in (401, 403):
        raise RuntimeError("OpenSubtitles rejected the API key. Check it in Settings")
    r.raise_for_status()
    release_words = set(re.split(r"[^a-z0-9]+", Path(video).stem.lower()))
    results = []
    for item in r.json().get("data", []):
        a = item["attributes"]
        if not a.get("files"):
            continue
        rel = a.get("release") or a["files"][0].get("file_name") or ""
        overlap = len(release_words & set(re.split(r"[^a-z0-9]+", rel.lower())))
        results.append({
            "file_id": a["files"][0]["file_id"],
            "release": rel,
            "downloads": a.get("download_count", 0),
            "hash_match": bool(a.get("moviehash_match")),
            "hearing_impaired": bool(a.get("hearing_impaired")),
            "trusted": bool(a.get("from_trusted")),
            "fps": a.get("fps"),
            "overlap": overlap,
        })
    results.sort(key=lambda x: (not x["hash_match"], x["hearing_impaired"], -x["overlap"], -x["downloads"]))
    return results


def download_subtitle(file_id):
    if not config.load()["opensubtitles_api_key"].strip():
        raise RuntimeError("Add a free OpenSubtitles API key in Settings to download subtitles")
    r = requests.post(f"{OS_API}/download", json={"file_id": file_id, "sub_format": "srt"},
                      headers={**_headers(), "Content-Type": "application/json"}, timeout=20)
    if r.status_code == 406:
        raise RuntimeError("OpenSubtitles daily download limit reached. Try again tomorrow, or generate instead")
    if r.status_code in (401, 403):
        raise RuntimeError("OpenSubtitles rejected the API key. Check it in Settings")
    r.raise_for_status()
    link = r.json()["link"]
    data = requests.get(link, timeout=30)
    data.raise_for_status()
    return _decode(data.content)


def _decode(raw):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


# --- syncing and shifting -------------------------------------------------------

def sync(job, video, srt_in, srt_out):
    """Line the subtitles up with the speech in the audio (ffsubsync). Returns the offset it found."""
    exe = Path(sys.executable).with_name("ffsubsync")
    tmp = Path(srt_out).with_suffix(".sync.tmp.srt")
    job.update(None, "Syncing to the audio", "Listening for speech and matching it to the subtitle timings")
    proc = subprocess.Popen([str(exe), str(video), "-i", str(srt_in), "-o", str(tmp),
                             "--ffmpeg-path", str(Path(ffmpeg()).parent)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    job.proc = proc
    log = proc.communicate()[0]
    job.proc = None
    if job.cancel_requested:
        raise jobs.Cancelled()
    if proc.returncode != 0 or not tmp.exists():
        tail = [l for l in log.splitlines() if l.strip()][-1:] or ["unknown error"]
        raise RuntimeError(f"Sync failed: {tail[0][-200:]}")
    tmp.replace(srt_out)
    m = re.search(r"offset seconds:\s*(-?[\d.]+)", log)
    scale = re.search(r"framerate scale factor:\s*([\d.]+)", log)
    offset = float(m.group(1)) if m else 0.0
    msg = f"Synced, moved by {offset:+.2f}s"
    if scale and abs(float(scale.group(1)) - 1) > 0.001:
        msg += f" and corrected the frame rate ({float(scale.group(1)):.4f}x)"
    job.update(None, msg)
    return offset


def shift(srt_in, srt_out, seconds):
    subs = list(srt.parse(_decode(Path(srt_in).read_bytes())))
    delta = datetime.timedelta(seconds=seconds)
    for s in subs:
        s.start = max(datetime.timedelta(0), s.start + delta)
        s.end = max(s.start, s.end + delta)
    Path(srt_out).write_text(srt.compose(subs), encoding="utf-8")


def extract_embedded(video, stream_index, srt_out):
    out = subprocess.run([ffmpeg(), "-y", "-v", "error", "-i", str(video), "-map", f"0:{stream_index}",
                          "-c:s", "srt", str(srt_out)], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("Couldn't read that subtitle track (picture-based subtitles can't be synced)")


# --- generating with Whisper ------------------------------------------------------

MLX_MODELS = {
    "tiny": "mlx-community/whisper-tiny-mlx", "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx", "medium": "mlx-community/whisper-medium-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}


def use_gpu():
    """Apple Silicon Macs run Whisper on the GPU through MLX, which is many times faster."""
    if sys.platform != "darwin" or os.uname().machine != "arm64":
        return False
    try:
        import mlx_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def generate(job, video, srt_out):
    """Transcribe the English audio locally: MLX on Apple Silicon, faster-whisper elsewhere."""
    model_name = config.load()["whisper_model"]
    duration = streams(video)[1] or 1
    job.update(0, "Reading the audio", "")
    audio = _audio_16k(video)
    segments = _transcribe_gpu(job, audio, model_name, duration) if use_gpu() else \
        _transcribe_cpu(job, audio, model_name, duration)
    subs = []
    for start, end, text in segments:
        text = text.strip()
        if text:
            subs.append(srt.Subtitle(len(subs) + 1, datetime.timedelta(seconds=start),
                                     datetime.timedelta(seconds=end), _wrap(text)))
    if not subs:
        raise RuntimeError("Whisper didn't hear any English speech")
    Path(srt_out).write_text(srt.compose(subs), encoding="utf-8")
    return len(subs)


def _transcribe_cpu(job, audio, model_name, duration):
    from faster_whisper import WhisperModel

    model_name = "large-v3-turbo" if model_name == "turbo" else model_name
    job.update(0, f"Loading the {model_name} speech model", "The first time downloads it")
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    job.update(0, "Transcribing the audio", "")
    segments, _ = model.transcribe(audio, language="en", vad_filter=True, beam_size=5, word_timestamps=True)
    words = []
    for seg in segments:
        words += [{"start": w.start, "end": w.end, "word": w.word} for w in (seg.words or [])]
        job.update(seg.end / duration, f"Transcribing · {int(seg.end) // 60} of {int(duration) // 60} min")
    return lines_from_words(words)


class _Progress:
    """Stands in for tqdm inside mlx_whisper, which is the only way it reports progress."""

    def __init__(self, job, duration):
        self.job, self.duration = job, duration

    def tqdm(self, total=None, **_):
        outer = self

        class Bar:
            n = 0

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def update(self, k):
                self.n += k
                done = self.n / total if total else 0
                mins = int(done * outer.duration) // 60
                outer.job.update(done, f"Transcribing on the GPU · {mins} of {int(outer.duration) // 60} min")

        return Bar()


def _transcribe_gpu(job, audio, model_name, duration):
    import mlx_whisper

    # the package exports a transcribe() function that hides the transcribe module, so look the module up
    mt = sys.modules["mlx_whisper.transcribe"]

    repo = MLX_MODELS.get(model_name, MLX_MODELS["turbo"])
    job.update(0, f"Loading the {model_name} speech model", "The first time downloads it")
    original = mt.tqdm
    mt.tqdm = _Progress(job, duration)
    try:
        result = mlx_whisper.transcribe(audio, path_or_hf_repo=repo, language="en", verbose=False,
                                        condition_on_previous_text=False, word_timestamps=True)
    finally:
        mt.tqdm = original
    return lines_from_words([w for s in result["segments"] for w in s.get("words", [])])


def lines_from_words(words, max_chars=84, max_seconds=6.0, pause=0.6):
    """Cut subtitle lines the way subtitle files are: at sentence ends, at pauses,
    and before a line gets longer than two rows or six seconds. Whisper's own
    segments often run several spoken lines together and start too early.
    On a 5 minute GOT clip this took 80% of lines from within 1.9s of the
    official timing to within 0.8s."""
    lines, cur = [], []

    def text(ws):
        return "".join(w["word"] for w in ws)

    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > pause or len(text(cur)) + len(w["word"]) > max_chars
                    or w["end"] - cur[0]["start"] > max_seconds):
            lines.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.?!]$", w["word"].strip()) and len(text(cur)) > 15:
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    return [(c[0]["start"], c[-1]["end"], text(c)) for c in lines]


def _audio_16k(video):
    """Mono 16 kHz float samples, decoded by ffmpeg. faster-whisper's own decoder
    breaks with PyAV 19 (it passes metadata_errors, which PyAV removed)."""
    import numpy as np

    out = subprocess.run([ffmpeg(), "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True)
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError("Couldn't read the audio from this file")
    return np.frombuffer(out.stdout, dtype=np.float32)


def _wrap(text, width=42):
    if len(text) <= width:
        return text
    words, line1 = text.split(), ""
    while words and len(line1) + len(words[0]) < len(text) / 2:
        line1 += (" " if line1 else "") + words.pop(0)
    return line1 + "\n" + " ".join(words)


# --- embedding ------------------------------------------------------------------------

def embed(job, video, srt_file):
    """Add the .srt as the default English track. Replaces an earlier Upnext track."""
    video = Path(video)
    codec = EMBEDDABLE.get(video.suffix.lower())
    if not codec:
        raise RuntimeError(f"Can't put subtitles inside a {video.suffix} file. The .srt next to it works in VLC")
    all_streams, duration = streams(video)
    subs = [s for s in all_streams if s.get("codec_type") == "subtitle"]
    args = [ffmpeg(), "-y", "-v", "error", "-i", str(video), "-i", str(srt_file), "-map", "0"]
    kept = 0
    for i, s in enumerate(subs):
        if s.get("tags", {}).get("title") == OUR_TITLE:
            args += ["-map", f"-0:s:{i}"]
        else:
            kept += 1
    args += ["-map", "1", "-c", "copy", f"-c:s:{kept}", codec,
             f"-metadata:s:s:{kept}", "language=eng", f"-metadata:s:s:{kept}", f"title={OUR_TITLE}"]
    for i in range(kept):
        args += [f"-disposition:s:{i}", "0"]
    args += [f"-disposition:s:{kept}", "default"]
    tmp = video.with_name(f".{video.stem}.upnext{video.suffix}")
    args += ["-progress", "pipe:1", "-nostats", str(tmp)]
    job.update(0, "Adding the subtitles to the video file", "")
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    job.proc = proc
    for line in proc.stdout:
        if line.startswith("out_time_us=") and duration:
            try:
                job.update(int(line.split("=")[1]) / 1e6 / duration)
            except ValueError:
                pass
    err = proc.stderr.read()
    proc.wait()
    job.proc = None
    if job.cancel_requested or proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        if job.cancel_requested:
            raise jobs.Cancelled()
        raise RuntimeError(f"ffmpeg couldn't embed the subtitles: {err.strip()[-200:]}")
    os.replace(tmp, video)
    job.update(1, "Embedded as the default English track")


# --- jobs the app queues ---------------------------------------------------------------

def _title(video, what):
    info = names.parse(Path(video).name)
    name = f"{info['series']} {names.code(info['season'], info['episode'])}" if info else Path(video).name
    return f"{what} · {name}"


def queue_auto(video):
    def run(job):
        s = config.load()
        if english_tracks(video):
            job.update(1, "Already has English subtitles inside")
            return
        out = sidecar(video)
        source = None
        existing = existing_sidecar(video)
        if existing:
            if existing != out:
                shutil.copyfile(existing, out)
            sync(job, video, out, out)
            source = "your .srt, synced"
        elif s["opensubtitles_api_key"].strip():
            job.update(None, "Searching OpenSubtitles")
            try:
                results = search(video)
            except (requests.RequestException, RuntimeError) as e:
                results = []
                job.update(None, f"Search failed: {e}")
            if results:
                best = results[0]
                job.update(None, f"Downloading {best['release'][:60]}")
                out.write_text(download_subtitle(best["file_id"]), encoding="utf-8")
                if best["hash_match"]:
                    job.update(None, "Exact match for this file, no sync needed")
                else:
                    sync(job, video, out, out)
                source = "OpenSubtitles" + ("" if best["hash_match"] else ", synced")
        if not source:
            if not s["generate_if_not_found"]:
                raise RuntimeError("No subtitles found online" if s["opensubtitles_api_key"] else
                                   "No OpenSubtitles API key, and generating is turned off")
            generate(job, video, out)
            source = "generated with Whisper"
        if s["embed_subtitles"] and Path(video).suffix.lower() in EMBEDDABLE:
            embed(job, video, out)
        job.update(1, f"English subtitles ready ({source})")

    return jobs.submit("subtitles", "subtitles", _title(video, "Subtitles"), run, key=f"subs:{video}")


def queue_fetch(video, file_id, hash_match=False):
    def run(job):
        out = sidecar(video)
        job.update(None, "Downloading from OpenSubtitles")
        out.write_text(download_subtitle(file_id), encoding="utf-8")
        if not hash_match:
            sync(job, video, out, out)
        if config.load()["embed_subtitles"] and Path(video).suffix.lower() in EMBEDDABLE:
            embed(job, video, out)
        job.update(1, "Subtitles replaced")

    return jobs.submit("subtitles", "subtitles", _title(video, "Subtitles"), run, key=f"subs:{video}")


def queue_sync(video, stream_index=None):
    """Fix out-of-sync subtitles: the .srt next to the video, or an embedded track."""
    def run(job):
        out = sidecar(video)
        if stream_index is not None:
            extract_embedded(video, stream_index, out)
        else:
            src = existing_sidecar(video)
            if not src:
                raise RuntimeError("No subtitles to sync. Find or generate some first")
            if src != out:
                shutil.copyfile(src, out)
        offset = sync(job, video, out, out)
        if config.load()["embed_subtitles"] and Path(video).suffix.lower() in EMBEDDABLE:
            embed(job, video, out)
        job.update(1, f"Synced ({offset:+.2f}s)")

    return jobs.submit("subtitles", "sync", _title(video, "Sync"), run, key=f"subs:{video}")


def queue_shift(video, seconds):
    def run(job):
        src = existing_sidecar(video)
        out = sidecar(video)
        if not src:
            eng = english_tracks(video)
            if not eng:
                raise RuntimeError("No subtitles to shift")
            extract_embedded(video, eng[-1]["index"], out)
            src = out
        shift(src, out, seconds)
        if config.load()["embed_subtitles"] and Path(video).suffix.lower() in EMBEDDABLE:
            embed(job, video, out)
        job.update(1, f"Shifted {seconds:+.1f}s")

    return jobs.submit("subtitles", "shift", _title(video, f"Shift {seconds:+.1f}s"), run, key=f"subs:{video}")


def queue_generate(video):
    def run(job):
        out = sidecar(video)
        n = generate(job, video, out)
        if config.load()["embed_subtitles"] and Path(video).suffix.lower() in EMBEDDABLE:
            embed(job, video, out)
        job.update(1, f"Generated {n} lines")

    return jobs.submit("subtitles", "generate", _title(video, "Generate"), run, key=f"subs:{video}")


def queue_embed(video):
    def run(job):
        src = existing_sidecar(video)
        if not src:
            raise RuntimeError("No .srt next to the video to embed")
        embed(job, video, src)

    return jobs.submit("subtitles", "embed", _title(video, "Embed"), run, key=f"subs:{video}")
