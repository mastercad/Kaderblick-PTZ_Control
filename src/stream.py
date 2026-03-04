"""
Live-Vorschau (RTSP, Low-Latency via mpv).

Kein Encoding, kein Skalieren — reiner Passthrough.
Nutzt die von ONVIF erkannte Sub-Stream URL (640x360 H264).
"""

import subprocess
import sys

import src.state as state
from src import onvif_ptz as ptz
from config.config import RTSP_MAIN


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
        # no: kein HW-Decode-Versuch → vermeidet VDPAU/CUDA/Vulkan-Warnungen
        # RPi4 schafft 640x360 H264 locker in Software
        '--hwdec=no',
        '--gpu-api=opengl',
        '--force-seekable=no',
        '--framedrop=decoder+vo',
        '--title=PTZ Live',
        url,
    ]


def _get_sub_stream_url():
    """
    Holt die Sub-Stream URL aus der ONVIF-Erkennung.
    Sucht nach 'subStream' in den erkannten Profilen.
    """
    for name, uri in ptz.stream_uris.items():
        if 'sub' in name.lower():
            return uri
    return None


def show():
    """
    Nutzt die ONVIF-erkannte Sub-Stream URL (640x360).
    Fällt auf Main-Stream zurück wenn kein Sub-Stream erkannt wurde.
    Kein Skalieren / kein Re-Encoding — reiner Passthrough.
    """
    # ONVIF-erkannte Sub-Stream URL verwenden
    sub_url = _get_sub_stream_url()

    if sub_url:
        print(f"Starte Live-Vorschau (ONVIF Sub-Stream): {sub_url}")
        cmd = _build_cmd(sub_url)
        state.stream_proc = subprocess.Popen(cmd, stderr=sys.stderr)
        retcode = state.stream_proc.wait()
        if retcode == 0:
            return   # Benutzer hat Fenster geschlossen → sauber beenden
        print(f"  → Sub-Stream fehlgeschlagen (exit {retcode})")
    else:
        print("  ⚠ Kein Sub-Stream per ONVIF erkannt!")

    # Fallback: Main-Stream (4K HEVC)
    print(f"Fallback → Main-Stream: {RTSP_MAIN}")
    cmd = _build_cmd(RTSP_MAIN)
    state.stream_proc = subprocess.Popen(cmd, stderr=sys.stderr)
    state.stream_proc.wait()
