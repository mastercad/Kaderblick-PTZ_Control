"""
Aufnahme (ffmpeg Main-Stream) und Screenshot.
"""

import os
import time
import signal
import subprocess
import threading

from src import overlay
import src.state as state
from config.config import RTSP_MAIN, RECORDING_DIR


def start():
    """Startet Aufnahme über Main-Stream in voller Qualität."""
    if state.ffmpeg_proc is not None:
        return
    filename = time.strftime('aufnahme_%Y%m%d_%H%M%S.mp4')
    filepath = os.path.join(RECORDING_DIR, filename)
    cmd = [
        'ffmpeg',
        '-rtsp_transport', 'tcp',
        '-i', RTSP_MAIN,
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-movflags', 'frag_keyframe+empty_moov',   # Crash-sicher!
        '-y', filepath
    ]
    state.ffmpeg_proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    state.recording = True
    print(f"🔴 Aufnahme gestartet: {filepath}")
    overlay.ensure_running()


def stop():
    """Stoppt laufende Aufnahme sauber."""
    if state.ffmpeg_proc is None:
        return
    state.ffmpeg_proc.send_signal(signal.SIGINT)
    try:
        state.ffmpeg_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        state.ffmpeg_proc.terminate()
        state.ffmpeg_proc.wait()
    state.ffmpeg_proc = None
    state.recording = False
    state.overlay_running = False
    print("⬛ Aufnahme gestoppt.")


def take_screenshot():
    """Screenshot im Hintergrund-Thread (blockiert nicht den Control-Loop)."""
    filename = time.strftime('screenshot_%Y%m%d_%H%M%S.jpg')
    filepath = os.path.join(RECORDING_DIR, filename)

    def _capture():
        cmd = [
            'ffmpeg', '-y',
            '-rtsp_transport', 'tcp',
            '-i', RTSP_MAIN,
            '-frames:v', '1',
            '-q:v', '2',
            filepath
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"📸 Screenshot: {filepath}")

    threading.Thread(target=_capture, daemon=True).start()
