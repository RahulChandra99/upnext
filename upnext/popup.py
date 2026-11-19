#!/usr/bin/env python3
"""Netflix-style "Up Next" card with a countdown.

Exits 0 to play the next episode (countdown ran out or Play Now clicked),
1 if cancelled. With --wait-file, waits for that file to finish downloading
(reach --size bytes) before the countdown starts. With --ready-url, also waits
until Upnext says the subtitles are done, so the next episode never starts
without them. Play Now still plays right away once the file is there.
"""

import argparse
import json
import os
import urllib.request
import sys
import tkinter as tk

BG = "#141414"
FG = "#ffffff"
MUTED = "#a3a3a3"
RED = "#e50914"
TRACK = "#3a3a3a"
W, H = 440, 172


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True, help='e.g. "S06E07 · The Broken Man"')
    ap.add_argument("--show", default="Game of Thrones")
    ap.add_argument("--seconds", type=int, default=15)
    ap.add_argument("--wait-file")
    ap.add_argument("--size", type=int, default=0)
    ap.add_argument("--ready-url", help="Upnext's /api/ready for the next episode")
    args = ap.parse_args()

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg=BG)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{W}x{H}+{sw - W - 40}+{sh - H - 110}")

    result = {"code": 1}

    def finish(code):
        result["code"] = code
        root.destroy()

    tk.Label(root, text="UP NEXT", bg=BG, fg=MUTED, font=("Helvetica Neue", 11, "bold")).place(x=22, y=16)
    tk.Label(root, text=args.title, bg=BG, fg=FG, font=("Helvetica Neue", 19, "bold"),
             anchor="w", width=30).place(x=20, y=36)
    status = tk.Label(root, text="", bg=BG, fg=MUTED, font=("Helvetica Neue", 13))
    status.place(x=22, y=70)

    bar = tk.Canvas(root, width=W - 44, height=4, bg=TRACK, highlightthickness=0)
    bar.place(x=22, y=98)
    fill = bar.create_rectangle(0, 0, 0, 4, fill=RED, width=0)

    # Labels instead of Buttons: macOS ignores Button colours
    def button(text, x, w, bg, fg, cmd):
        b = tk.Label(root, text=text, bg=bg, fg=fg, font=("Helvetica Neue", 14, "bold"),
                     width=w, pady=7, cursor="hand2")
        b.place(x=x, y=118)
        b.bind("<Button-1>", lambda e: cmd())
        return b

    button("▶  Play Now", 22, 13, FG, "#000000", lambda: downloaded() and finish(0))
    button("Cancel", 200, 9, "#333333", FG, lambda: finish(1))
    root.bind("<Escape>", lambda e: finish(1))
    root.bind("<Return>", lambda e: downloaded() and finish(0))

    def downloaded():
        if not args.wait_file:
            return True
        try:
            return os.path.getsize(args.wait_file) >= args.size
        except OSError:
            return False

    def subtitles():
        """(ready, message). If Upnext can't be reached, don't hold the episode hostage."""
        if not args.ready_url:
            return True, ""
        try:
            with urllib.request.urlopen(args.ready_url, timeout=2) as r:
                d = json.load(r)
            return d["ready"], d.get("message", "")
        except Exception:
            return True, ""

    total = args.seconds * 10  # ticks of 100ms
    state = {"left": total}

    def tick():
        if not downloaded():
            status.config(text=f"Downloading {args.show} episode…")
            bar.coords(fill, 0, 0, 0, 4)
            root.after(500, tick)
            return
        if not state.get("subs_ready"):
            ok, msg = subtitles()
            if not ok:
                status.config(text=(msg or "Getting subtitles ready")[:52] + "…")
                bar.coords(fill, 0, 0, 0, 4)
                root.after(1000, tick)
                return
            state["subs_ready"] = True
        left = state["left"]
        status.config(text=f"{args.show}  ·  Playing in {max(1, -(-left // 10))}")
        bar.coords(fill, 0, 0, (W - 44) * (total - left) / total, 4)
        if left <= 0:
            finish(0)
            return
        state["left"] -= 1
        root.after(100, tick)

    tick()
    root.lift()
    root.mainloop()
    sys.exit(result["code"])


if __name__ == "__main__":
    main()
