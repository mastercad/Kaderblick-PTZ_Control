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
    """mpv-Kommando: absolute Minimal-Latenz für 640x360 H264."""
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
            'rtsp_transport=udp,'         # UDP statt TCP → weniger Latenz
            'analyzeduration=0,'           # Sofort loslegen
            'probesize=1024',              # Absolutes Minimum
        '--demuxer-readahead-secs=0',      # Kein Buffer
        '--interpolation=no',
        '--video-latency-hacks=yes',
        '--vd-lavc-threads=1',             # 1 Thread = kein Frame-Reordering-Delay
        '--vd-lavc-o=flags=+low_delay',    # Low-Delay Decoding
        '--no-correct-pts',                # Kein PTS-Sorting → sofort anzeigen
        '--hwdec=no',
        '--gpu-api=opengl',
        '--opengl-swapinterval=0',         # Kein VSync-Warten
        '--force-seekable=no',
        '--framedrop=vo',
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
