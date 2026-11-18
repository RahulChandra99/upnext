@echo off
rem Windows: double-click to set up (first time) and start Upnext.
rem Needs Python 3.11+ from python.org, plus ffmpeg, rclone and VLC:
rem   winget install Gyan.FFmpeg Rclone.Rclone VideoLAN.VLC
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw -m upnext
