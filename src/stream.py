"""
Live-Vorschau (RTSP, Low-Latency via mpv).

Kein Encoding, kein Skalieren — reiner Passthrough.
RPi 4: --hwdec=auto-copy + --gpu-api=opengl (Vulkan hat OOM bei 4K).
"""

import subprocess
import sys

import src.state as state
from config.config import CAMERA_IP, USERNAME, PASSWORD, RTSP_MAIN

# Alle bekannten Sub-Stream URLs für XM/Xiongmai-Kameras
# (probe_streams.py kann die richtige ermitteln)
_AUTH = f"{USERNAME}:{PASSWORD}@" if PASSWORD else f"{USERNAME}@"
_SUB_STREAM_URLS = [
    f"rtsp://{_AUTH}{CAMERA_IP}:554/stream2",
    # XM SDP-Stil: stream=1 = Sub-Stream
    f"rtsp://{_AUTH}{CAMERA_IP}:554/user={USERNAME}&password={PASSWORD}&channel=1&stream=1.sdp",
    # XM numerisch: 12 = Kanal 1, Stream 2 (sub)
    f"rtsp://{_AUTH}{CAMERA_IP}:554/12",
]


def _build_cmd(url):
    """mpv-Kommando: reiner Passthrough, KEIN Re-Encoding/Skalieren."""
    return [
        'mpv',
        '--fullscreen',
        '--no-audio',
        '--profile=low-latency',
        '--cache=no',
        '--cache-pause=no',
        # WICHTIG: --demuxer-lavf-o darf nur EINMAL vorkommen!
        '--demuxer-lavf-o='
            'fflags=+nobuffer+fastseek+discardcorrupt,'
            'rtsp_transport=tcp,'
            'analyzeduration=500000,'
            'probesize=65536',
        '--demuxer-readahead-secs=0.5',
        '--interpolation=no',
        '--video-latency-hacks=yes',
        '--vd-lavc-threads=4',
        '--hwdec=auto-copy',
        '--gpu-api=opengl',
        '--force-seekable=no',
        '--framedrop=decoder+vo',
        '--title=PTZ Live',
        url,
    ]


def show():
    """
    Probiert Sub-Stream URLs, fällt auf Main-Stream zurück.
    Kein Skalieren / kein Re-Encoding — reiner Passthrough.
    """
    # Sub-Stream versuchen (niedrigere Auflösung → RPi4 schafft es locker)
    for i, url in enumerate(_SUB_STREAM_URLS):
        label = f"Sub-Stream URL {i+1}/{len(_SUB_STREAM_URLS)}"
        print(f"Versuche {label}: {url}")
        cmd = _build_cmd(url)
        state.stream_proc = subprocess.Popen(cmd, stderr=sys.stderr)
        retcode = state.stream_proc.wait()
        if retcode == 0:
            return   # Benutzer hat Fenster geschlossen → sauber beenden
        print(f"  → {label} fehlgeschlagen (exit {retcode})")

    # Fallback: Main-Stream (4K HEVC — ohne Filter, RPi4 muss es schaffen)
    print(f"Kein Sub-Stream verfügbar → Main-Stream: {RTSP_MAIN}")
    print("  TIPP: probe_streams.py auf dem Pi ausführen um die richtige URL zu finden!")
    cmd = _build_cmd(RTSP_MAIN)
    state.stream_proc = subprocess.Popen(cmd, stderr=sys.stderr)
    state.stream_proc.wait()
