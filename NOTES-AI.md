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

## 2026-11-18, S07E04 subtitles that wouldn't sync

**Picture subtitles counted as "already has English".** The S07E04 MP4 has 14 English tracks: 12 DVD picture tracks, a one-line forced track, and nothing with real dialogue. Fix automatically checked the language tag only, so every press said "Already has English subtitles inside" and did nothing. Fix: only text tracks with at least 50 lines count.

**Trusted ffsubsync when it was pinned at its limit.** My .srt was 84 seconds late. ffsubsync searches 60 seconds by default, returned -59.99, and the app wrote that as a fix, still 24 seconds off, and embedded it. Run again, it "corrected" the frame rate instead and spread the error from 38 to 120 seconds across the episode. Caught by measuring against the speech: Whisper transcript, 228 lines matched to the .srt, a straight-line fit gave -83.85s with no drift, and 0.14s median error after correcting. Fix in the app: `--no-fix-framerate`, and a result at the limit is refused with nothing changed. The Whisper-anchored fit is now the app's sync engine (next entry).

**MP4 track names are stored differently.** MKV keeps the track name as `title`, MP4 as `name` or `handler_name`, and a plain remux drops `name`. So the app couldn't recognise its own earlier track and left the wrong one in the file next to the new one. Fix: check all three tags, and write `handler_name` too, which survives a remux.

**Sync wrote its copy before it knew it worked.** It copied the .srt to .en.srt, then synced in place, so a failed sync left an unsynced .en.srt that VLC would load. Now it reads the original and only writes .en.srt on success.

## 2026-11-19, Whisper-anchored sync

Built the method from the S07E04 fix into the Sync button (`align.py`). Lines are matched to the Whisper transcript on their first four words, only when those words are unique to one line, then a straight line is fitted with outliers dropped. If that fits badly, a piecewise offset handles cuts. Tested on synthetic offsets, a speed change, a 40 second cut and a wrong episode, then on the real file: -83.80s against the -83.85s found by hand, all 495 lines within 0.3s of the verified version.

**My first comparison said one line was 895 seconds off.** It wasn't. The check looked lines up by their text, and lines like "Yes." appear more than once. Compared in order, every line matched. Worth remembering before trusting or panicking about a "max error".

**Sync picked the file for me.** With both `.srt` and `.en.srt` next to the video it always took `.en.srt`, which was the wrong one when I wanted mine synced. The Sync card now has a picker with every `.srt` for that episode and any text track inside it.

## 2026-11-19, subtitles ready before the next episode

**Shipped a race as a "known gap".** The first Upnext queued subtitles after the download and autoplayed whenever the download finished, so an episode could start while Whisper was still working and VLC never picked the subtitles up. It was written down in the README instead of fixed. Now the Up Next card asks the app whether the episode's subtitle job is done and holds the countdown until it is. The next episode's download and subtitles are also marked urgent so they jump a queued season, and the prefetch default went from 15 to 20 minutes so the wait is rare: download plus Whisper small is about 8 minutes on my connection.
