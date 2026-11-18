# What AI got wrong

A running log. What Claude generated, what was wrong with it, how it was caught, how it was fixed.

## 2026-11-02, the GOT script this grew out of

**Tried to download a private Drive folder anonymously.** First attempt used gdown, which only works on folders shared as "anyone with the link". Mine is private, so it failed with a 401. Fix: rclone with a read-only Google sign-in.

**Claimed rclone resumes interrupted downloads.** The first README said a stopped download picks up where it left off. It doesn't. rclone writes to a `.partial` file and starts that file over. Caught while re-reading the code against the docs, and the claim was removed before I relied on it.

**One download stream was slow.** 2.6 MB/s on a single stream. Measured 1, 4 and 16 parallel streams on the same file for 20 seconds each, and 16 gave about 10 MB/s. Upnext still uses 16.

**Wanted to time the credits off the last subtitle.** That was my idea, and Claude checked it against a real file before agreeing. In S06E05 the last subtitle sits 10 seconds inside the credits, so the card would have been late. Black frame detection found the cut to the exact second, so that's what Upnext uses.

## 2026-11-18, turning it into Upnext

**The OpenSubtitles API worked once without a key, then stopped.** The first probe with curl returned 16 results, so the plan was "search free, key only to download". Twenty minutes later every search got "You cannot consume this service". Caught by the Search button in the app returning 403. Fix: the app now says a key is needed for searching too, and without one it goes straight to Whisper.

**Podnapisi as a no-key subtitle source.** Planned as the backup provider. It doesn't resolve on my network (blocked at DNS, and TLS fails even with the IP). Dropped rather than shipping a provider that silently never works here.

**faster-whisper crashed on the current PyAV.** `open() got an unexpected keyword argument 'metadata_errors'`. faster-whisper 1.2.1 passes an argument PyAV 19 removed. Caught on the first real subtitle job after a download. Fix: decode the audio with ffmpeg into a numpy array and hand Whisper the samples, which takes PyAV out of the path entirely instead of pinning an old version.

**CPU Whisper was too slow to be the default on a Mac.** The small model did about 12 minutes of audio in 5 minutes, so a full episode would take around 20. Switched Apple Silicon to mlx-whisper on the GPU. faster-whisper stays for Windows and Linux.

**Assumed the biggest GPU model would be fast enough.** Claude made large-v3-turbo the Mac default without timing it. A full episode ran past 12 minutes and looked stuck. Timed a 5 minute clip instead: turbo 62s, small 31s, base 12s, all writing the same lines. Also found `condition_on_previous_text=True` made turbo 65% slower (103s) and padded it with extra segments. Default is now small with that option off.

**Settings froze the defaults.** The first config code wrote every default into settings.json the first time it ran, so changing a default in a later version would never reach an existing install. Caught when changing the Whisper default to turbo. Fix: only settings you've actually changed are stored.

**Name parsing missed common layouts.** `Show/Season 1/S01E02.mkv` lost the show name, `breaking_bad_3x07` wasn't recognised because `\b` doesn't fire after an underscore, and "The Office US" became "The Office Us". Caught by a quick table of real-world file names before building on it.
