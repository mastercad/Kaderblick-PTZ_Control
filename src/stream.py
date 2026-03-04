"""
Live-Vorschau (RTSP, Low-Latency via mpv).

RPi 4 Besonderheiten:
  - Vulkan (default gpu VO) → VK_ERROR_OUT_OF_HOST_MEMORY bei 4K
    → --gpu-api=opengl erzwingen
  - 4K HEVC zu schwer für RPi4 GPU → --vf=scale herunterskalieren
  - drm_prime mapping kaputt → --hwdec=auto-copy (Frames→RAM)
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


def _build_cmd(url, scale_down=False):
    """mpv-Kommando mit Low-Latency-Einstellungen für Live-RTSP."""
    cmd = [
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
        # OpenGL statt Vulkan — Vulkan hat auf RPi4 OOM bei 4K
        '--gpu-api=opengl',
        '--force-seekable=no',
        '--framedrop=decoder+vo',
        '--title=PTZ Live',
    ]
    # 4K → 960p skalieren damit RPi4 GPU es schafft
    if scale_down:
        cmd.append('--vf=lavfi=[scale=960:-2]')
    cmd.append(url)
    return cmd


def show():
    """
    Versucht Sub-Stream URLs, fällt auf Main-Stream (skaliert) zurück.
    stderr wird durchgereicht damit mpv-Fehler sichtbar bleiben.
    """
    # Sub-Stream versuchen (niedrigere Auflösung → kein Scale nötig)
    for i, url in enumerate(_SUB_STREAM_URLS):
        label = f"Sub-Stream URL {i+1}/{len(_SUB_STREAM_URLS)}"
        print(f"Versuche {label}: {url}")
        cmd = _build_cmd(url, scale_down=False)
        state.stream_proc = subprocess.Popen(cmd, stderr=sys.stderr)
        retcode = state.stream_proc.wait()
        if retcode == 0:
            return   # Benutzer hat Fenster geschlossen → sauber beenden
        print(f"  → {label} fehlgeschlagen (exit {retcode})")

    # Fallback: Main-Stream mit Downscale (4K→960p, sonst OOM auf RPi4)
    print(f"Alle Sub-Streams fehlgeschlagen, versuche Main-Stream (skaliert): {RTSP_MAIN}")
    cmd = _build_cmd(RTSP_MAIN, scale_down=True)
    state.stream_proc = subprocess.Popen(cmd, stderr=sys.stderr)
    state.stream_proc.wait()
