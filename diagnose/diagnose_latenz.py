#!/usr/bin/env python3
"""
Stream-Latenz Vergleich: mpv vs ffplay.
Testet auch RTSP/UDP vs RTSP/TCP und zeigt Stream-Info.
"""

import subprocess
import sys
import os

sys.path.insert(0, '.')
from config.config import CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD

# ONVIF Sub-Stream URL ermitteln
from onvif import ONVIFCamera
print("ONVIF-Verbindung...", flush=True)
cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
media = cam.create_media_service()
profiles = media.GetProfiles()
sub_url = None
for p in profiles:
    if 'sub' in p.Name.lower():
        uri_resp = media.GetStreamUri({
            'StreamSetup': {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}},
            'ProfileToken': p.token,
        })
        sub_url = uri_resp.Uri
        vec = p.VideoEncoderConfiguration
        if vec:
            print(f"  Sub-Stream: {vec.Resolution.Width}x{vec.Resolution.Height} {vec.Encoding}")
            if hasattr(vec, 'RateControl'):
                rc = vec.RateControl
                print(f"  FPS: {rc.FrameRateLimit}  Bitrate: {rc.BitrateLimit}kbps")
            if hasattr(vec, 'GovLength'):
                print(f"  GOP-Länge: {vec.GovLength}")
            if hasattr(vec, 'H264') and vec.H264:
                print(f"  H264-Profil: {vec.H264.H264Profile}")
                if hasattr(vec.H264, 'GovLength'):
                    print(f"  H264 GOP: {vec.H264.GovLength}")
        break

if not sub_url:
    print("FEHLER: Kein Sub-Stream gefunden!")
    sys.exit(1)

print(f"\nURL: {sub_url}\n")

# ffprobe: Stream-Details
print("=" * 60)
print("FFPROBE: Stream-Details")
print("=" * 60)
subprocess.run([
    'ffprobe', '-rtsp_transport', 'tcp',
    '-v', 'error', '-show_streams',
    '-select_streams', 'v:0',
    '-print_format', 'flat',
    sub_url
], timeout=10)

print()
print("=" * 60)
print("Wähle Test:")
print("  1 = mpv (aktuelle Settings)")
print("  2 = ffplay UDP (minimal-latenz)")
print("  3 = ffplay TCP")
print("  4 = mpv mit --no-correct-pts --profile=low-latency --untimed")
print("=" * 60)

choice = input("Auswahl (1-4): ").strip()

if choice == "1":
    cmd = [
        'mpv', '--fullscreen', '--no-audio',
        '--profile=low-latency',
        '--cache=no', '--cache-pause=no',
        '--demuxer-lavf-o='
            'fflags=+nobuffer+fastseek+discardcorrupt,'
            'rtsp_transport=udp,'
            'analyzeduration=0,'
            'probesize=1024',
        '--demuxer-readahead-secs=0',
        '--interpolation=no', '--video-latency-hacks=yes',
        '--vd-lavc-threads=1',
        '--vd-lavc-o=flags=+low_delay',
        '--no-correct-pts',
        '--hwdec=no', '--gpu-api=opengl',
        '--opengl-swapinterval=0',
        '--framedrop=vo',
        sub_url,
    ]
elif choice == "2":
    cmd = [
        'ffplay',
        '-fflags', 'nobuffer+fastseek+discardcorrupt',
        '-flags', 'low_delay',
        '-rtsp_transport', 'udp',
        '-analyzeduration', '0',
        '-probesize', '1024',
        '-sync', 'ext',
        '-framedrop',
        '-fast',
        '-infbuf',
        '-fs',
        sub_url,
    ]
elif choice == "3":
    cmd = [
        'ffplay',
        '-fflags', 'nobuffer+fastseek+discardcorrupt',
        '-flags', 'low_delay',
        '-rtsp_transport', 'tcp',
        '-analyzeduration', '0',
        '-probesize', '32768',
        '-sync', 'ext',
        '-framedrop',
        '-fast',
        '-infbuf',
        '-fs',
        sub_url,
    ]
elif choice == "4":
    cmd = [
        'mpv', '--fullscreen', '--no-audio',
        '--profile=low-latency',
        '--cache=no', '--cache-pause=no',
        '--demuxer-lavf-o='
            'fflags=+nobuffer+fastseek+discardcorrupt,'
            'rtsp_transport=udp,'
            'analyzeduration=0,'
            'probesize=1024',
        '--demuxer-readahead-secs=0',
        '--interpolation=no', '--video-latency-hacks=yes',
        '--vd-lavc-threads=1',
        '--vd-lavc-o=flags=+low_delay',
        '--no-correct-pts',
        '--untimed',
        '--hwdec=no', '--gpu-api=opengl',
        '--opengl-swapinterval=0',
        '--framedrop=decoder+vo',
        sub_url,
    ]
else:
    print("Ungültige Auswahl")
    sys.exit(1)

print(f"\nStarte: {' '.join(cmd)}\n")
subprocess.run(cmd)
