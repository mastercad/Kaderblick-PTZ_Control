"""
Live-Vorschau (Sub-Stream, Low-Latency via mpv).

RPi 4:
  --hwdec=auto-copy  → HW-Decode, Frames→RAM (kein DRM dmabuf nötig)
  NICHT --untimed    → für Live-RTSP ungeeignet (friert ein!)
"""

import subprocess
import sys

import src.state as state
from config.config import RTSP_SUB, RTSP_MAIN

# Verschiedene Sub-Stream URLs die Xiongmai/XM-Kameras nutzen können
_SUB_STREAM_URLS = [
    RTSP_SUB,                                               # /stream2
    RTSP_SUB.replace('/stream2', '/cam/realmonitor?channel=1&subtype=1'),
    RTSP_SUB.replace('/stream2', '/h264/ch1/sub/av_stream'),
]


def _build_cmd(url):
    """mpv-Kommando mit Low-Latency-Einstellungen für Live-RTSP."""
    # WICHTIG: --demuxer-lavf-o darf nur EINMAL vorkommen (letzter gewinnt!)
    return [
        'mpv',
        '--fullscreen',
        '--no-audio',
        '--profile=low-latency',
        # KEIN --untimed! Das ist für Dateien, nicht Live-Streams.
        # Bei RTSP friert es nach dem 1. Frame ein.
        '--cache=no',
        '--cache-pause=no',
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
        '--force-seekable=no',
        '--framedrop=decoder+vo',
        '--title=PTZ Live',
        url,
    ]


def show():
    """
    Versucht Sub-Stream URLs, fällt auf Main-Stream zurück.
    stderr wird durchgereicht damit mpv-Fehler sichtbar bleiben.
    """
    # Sub-Stream versuchen (niedrigere Auflösung für flüssige Vorschau)
    for i, url in enumerate(_SUB_STREAM_URLS):
        label = f"Sub-Stream URL {i+1}/{len(_SUB_STREAM_URLS)}"
        print(f"Versuche {label}: {url}")
        cmd = _build_cmd(url)
        state.stream_proc = subprocess.Popen(cmd, stderr=sys.stderr)
        retcode = state.stream_proc.wait()
        if retcode == 0:
            return   # Benutzer hat Fenster geschlossen → sauber beenden
        print(f"  → {label} fehlgeschlagen (exit {retcode})")

    # Fallback: Main-Stream (4K, schwerer für RPi4 aber besser als nichts)
    print(f"Alle Sub-Streams fehlgeschlagen, versuche Main-Stream: {RTSP_MAIN}")
    cmd = _build_cmd(RTSP_MAIN)
    state.stream_proc = subprocess.Popen(cmd, stderr=sys.stderr)
    state.stream_proc.wait()
