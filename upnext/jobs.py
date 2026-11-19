"""Background jobs with progress, shown on the Activity page.

Two lanes: downloads run two at a time, subtitle work runs one at a time
(syncing and Whisper are CPU heavy and would fight over the cores).
Urgent jobs (the episode you're about to watch) go ahead of everything queued.
"""

import itertools
import queue
import threading
import time
import traceback

_ids = itertools.count(1)
_jobs = {}
_lock = threading.Lock()
LANES = {"download": 2, "subtitles": 1}
_queues = {lane: queue.PriorityQueue() for lane in LANES}


class Cancelled(Exception):
    pass


class Job:
    def __init__(self, lane, kind, title, fn, key=None):
        self.id = next(_ids)
        self.lane, self.kind, self.title, self.fn, self.key = lane, kind, title, fn, key
        self.status = "queued"  # queued, running, done, failed, cancelled
        self.progress = None  # 0..1, or None when unknown
        self.message = "Waiting"
        self.detail = ""
        self.result = None
        self.created = time.time()
        self.finished = None
        self.cancel_requested = False
        self.proc = None  # a running subprocess, killed on cancel

    def update(self, progress=None, message=None, detail=None):
        if self.cancel_requested:
            raise Cancelled()
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        if message is not None:
            self.message = message
        if detail is not None:
            self.detail = detail

    def as_json(self):
        return {k: getattr(self, k) for k in
                ("id", "lane", "kind", "title", "status", "progress", "message", "detail", "created", "finished", "key")}


def submit(lane, kind, title, fn, key=None, urgent=False):
    """Queue fn(job). A job with the same key that's still queued or running is reused
    (and moved to the front if this request is urgent)."""
    with _lock:
        if key:
            for j in _jobs.values():
                if j.key == key and j.status in ("queued", "running"):
                    if urgent and j.status == "queued":
                        _queues[lane].put((0, j.id, j))  # the old entry is skipped once this one runs
                    return j
        job = Job(lane, kind, title, fn, key)
        _jobs[job.id] = job
    _queues[lane].put((0 if urgent else 1, job.id, job))
    return job


def cancel(job_id):
    job = _jobs.get(job_id)
    if not job:
        return False
    job.cancel_requested = True
    if job.status == "queued":
        job.status, job.message, job.finished = "cancelled", "Cancelled", time.time()
    if job.proc and job.proc.poll() is None:
        job.proc.terminate()
    return True


def find(key):
    with _lock:
        for j in sorted(_jobs.values(), key=lambda j: -j.id):
            if j.key == key:
                return j
    return None


def active(key):
    j = find(key)
    return j if j and j.status in ("queued", "running") else None


def listing():
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: -j.id)
    # keep the list short: everything active plus the 30 most recent finished
    done = [j for j in jobs if j.status not in ("queued", "running")][:30]
    return [j.as_json() for j in jobs if j.status in ("queued", "running")] + [j.as_json() for j in done]


def clear_finished():
    with _lock:
        for jid in [i for i, j in _jobs.items() if j.status not in ("queued", "running")]:
            del _jobs[jid]


def _worker(lane):
    q = _queues[lane]
    while True:
        _, _, job = q.get()
        if job.status != "queued":  # cancelled, or a duplicate entry from being made urgent
            continue
        job.status, job.message = "running", "Starting"
        try:
            job.result = job.fn(job)
            job.status = "done"
            if job.message in ("Starting",):
                job.message = "Done"
        except Cancelled:
            job.status, job.message = "cancelled", "Cancelled"
        except Exception as e:
            if job.cancel_requested:
                job.status, job.message = "cancelled", "Cancelled"
            else:
                job.status, job.message = "failed", str(e) or e.__class__.__name__
                job.detail = traceback.format_exc(limit=3)
        job.finished = time.time()


def start():
    for lane, n in LANES.items():
        for _ in range(n):
            threading.Thread(target=_worker, args=(lane,), daemon=True).start()
