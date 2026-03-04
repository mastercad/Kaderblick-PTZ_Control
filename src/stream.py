"""
Live-Vorschau (Sub-Stream, Low-Latency via mpv).
"""

import subprocess
import sys

import src.state as state
from config.config import RTSP_SUB, RTSP_MAIN


def _build_cmd(url):
    """mpv-Kommando mit Low-Latency-Einstellungen zusammenbauen."""
    # WICHTIG: --demuxer-lavf-o darf nur EINMAL vorkommen (letzter gewinnt!)
    # probesize & analyzeduration müssen groß genug sein um den Codec zu
    # erkennen — zu kleine Werte (z.B. 32) führen zu blauem Bild!
    return [
        'mpv',
        '--fullscreen',
        '--no-audio',
        '--profile=low-latency',
        '--untimed',
        '--no-cache',
        '--cache-pause=no',
        '--demuxer-lavf-o='
            'fflags=+nobuffer+fastseek,'
            'rtsp_transport=tcp,'
            'analyzeduration=500000,'   # 0.5 s — Kompromiss Latenz/Erkennung
            'probesize=65536',          # 64 KB — genug für Codec-Erkennung
        '--demuxer-readahead-secs=0.2',
        '--interpolation=no',
        '--video-sync=display-resample',
        '--video-latency-hacks=yes',
        '--vd-lavc-threads=4',
        '--hwdec=auto-safe',
        '--force-seekable=no',
        '--framedrop=decoder+vo',
        '--display-fps-override=30',
        '--title=PTZ Live',
        url,
    ]


def show():
    """
    Zeigt den Sub-Stream. Fällt auf Main-Stream zurück.
    stderr wird durchgereicht damit mpv-Fehler sichtbar bleiben.
    """
    print(f"Starte Live-Vorschau (Sub-Stream): {RTSP_SUB}")
    cmd = _build_cmd(RTSP_SUB)
    state.stream_proc = subprocess.Popen(cmd, stderr=sys.stderr)
    retcode = state.stream_proc.wait()

    # Fallback auf Main-Stream
    if retcode != 0:
        print(f"Sub-Stream fehlgeschlagen (exit {retcode}), versuche Main-Stream: {RTSP_MAIN}")
        cmd = _build_cmd(RTSP_MAIN)
        state.stream_proc = subprocess.Popen(cmd, stderr=sys.stderr)
        state.stream_proc.wait()
