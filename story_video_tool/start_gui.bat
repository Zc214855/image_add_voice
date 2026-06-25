@echo off
setlocal
cd /d "%~dp0\.."
pythonw story_video_tool\gui.py
if errorlevel 1 python story_video_tool\gui.py

