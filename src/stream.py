"""
Live-Vorschau (Sub-Stream, Low-Latency via mpv).
"""

import subprocess

import src.state as state
from config.config import RTSP_SUB, RTSP_MAIN


def show():
    """
    Zeigt den Sub-Stream mit aggressiven Low-Latency-Einstellungen.
    Fällt auf Main-Stream zurück wenn Sub-Stream nicht verfügbar.
    """
    # WICHTIG: --demuxer-lavf-o darf nur EINMAL vorkommen (letzter gewinnt!)
    cmd = [
        'mpv',
        '--fullscreen',
        '--no-audio',
        '--profile=low-latency',
        '--untimed',
        '--no-cache',
        '--cache-pause=no',
        '--demuxer-lavf-o=fflags=+nobuffer+fastseek,rtsp_transport=tcp,analyzeduration=0,probesize=32',
        '--demuxer-readahead-secs=0',
        '--interpolation=no',
        '--video-sync=display-resample',
        '--video-latency-hacks=yes',
        '--vd-lavc-threads=4',
        '--hwdec=auto-safe',
        '--force-seekable=no',
        '--framedrop=decoder+vo',
        '--display-fps-override=30',
        '--title=PTZ Live',
        RTSP_SUB
    ]

    print("Starte Live-Vorschau (Sub-Stream)...")
    state.stream_proc = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
    retcode = state.stream_proc.wait()

    # Fallback auf Main-Stream
    if retcode != 0:
        print("Sub-Stream nicht verfügbar, versuche Main-Stream...")
        cmd[-1] = RTSP_MAIN
        state.stream_proc = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
        state.stream_proc.wait()
