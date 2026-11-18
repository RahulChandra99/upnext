#!/bin/sh
# One-time setup on macOS or Linux: Python environment plus ffmpeg and rclone.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

if command -v brew >/dev/null 2>&1; then
  command -v ffmpeg >/dev/null 2>&1 || brew install ffmpeg
  command -v rclone >/dev/null 2>&1 || brew install rclone
  [ -d /Applications/VLC.app ] || brew install --cask vlc
else
  command -v ffmpeg >/dev/null 2>&1 || echo "Install ffmpeg with your package manager (apt install ffmpeg)"
  command -v rclone >/dev/null 2>&1 || echo "Install rclone: https://rclone.org/install/"
  command -v vlc >/dev/null 2>&1 || echo "Install VLC: https://www.videolan.org"
fi
echo "Setup done. Start Upnext with: .venv/bin/python -m upnext"
