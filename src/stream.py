"""
Live-Vorschau (Sub-Stream, Low-Latency via mpv).

RPi 4 Besonderheit:
  --hwdec=auto-safe wählt 'drm' → drm_prime Frames → gpu VO kann die
  DRM-Modifier nicht mappen → blaues Bild + "mapping DRM dmabuf failed".
  Lösung: --hwdec=auto-copy  (HW-Decode, aber Frames werden ins RAM kopiert).
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
    """mpv-Kommando mit Low-Latency-Einstellungen zusammenbauen."""
    # WICHTIG: --demuxer-lavf-o darf nur EINMAL vorkommen (letzter gewinnt!)
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
            'analyzeduration=500000,'   # 0.5 s reichen für Codec-Erkennung
            'probesize=65536',          # 64 KB
        '--demuxer-readahead-secs=0.2',
        '--interpolation=no',
        # Kein --video-sync bei --untimed + --no-audio (RTSP hat oft keine PTS)
        '--video-latency-hacks=yes',
        '--vd-lavc-threads=4',
        # auto-copy: HW-Decode, aber Frames→RAM kopieren (vermeidet
        # drm_prime/dmabuf-Fehler auf RPi 4)
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
