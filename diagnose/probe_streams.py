#!/usr/bin/env python3
"""
Probiert alle bekannten RTSP-URLs einer XM/Xiongmai-Kamera durch
und zeigt an welche funktionieren + deren Codec/Auflösung.

Aufruf:  python3 probe_streams.py
         python3 probe_streams.py 192.168.178.122
"""

import subprocess
import sys

CAMERA_IP = sys.argv[1] if len(sys.argv) > 1 else '192.168.178.122'
USERNAME  = 'admin'
PASSWORD  = ''

# Alle bekannten RTSP-URL-Varianten für XM/Xiongmai-Kameras
URLS = [
    # Standard XM
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/stream",
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/stream2",
    # XM SDP-Stil (stream=0 main, stream=1 sub)
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/user={USERNAME}&password={PASSWORD}&channel=1&stream=0.sdp",
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/user={USERNAME}&password={PASSWORD}&channel=1&stream=1.sdp",
    # XM numerisch (11=ch1 main, 12=ch1 sub)
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/11",
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/12",
    # Dahua-Stil
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/cam/realmonitor?channel=1&subtype=0",
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/cam/realmonitor?channel=1&subtype=1",
    # ONVIF-generisch
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/h264/ch1/main/av_stream",
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/h264/ch1/sub/av_stream",
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/h265/ch1/main/av_stream",
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/h265/ch1/sub/av_stream",
    # Hikvision-Stil (manche XM-Klone)
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/Streaming/Channels/101",
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/Streaming/Channels/102",
    # XM /live
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/live/main",
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/live/sub",
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/live/ch00_1",
    f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/live/ch00_0",
]


def probe_url(url, timeout=5):
    """Prüft eine RTSP-URL mit ffprobe und gibt Stream-Info zurück."""
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-rtsp_transport', 'tcp',
        '-analyzeduration', '2000000',
        '-probesize', '100000',
        '-print_format', 'json',
        '-show_streams',
        '-timeout', str(timeout * 1000000),
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        if result.returncode == 0 and '"codec_type"' in result.stdout:
            return result.stdout
    except subprocess.TimeoutExpired:
        pass
    return None


def main():
    print(f"Probe RTSP-Streams auf {CAMERA_IP}...")
    print(f"{'='*70}")
    found = []

    for i, url in enumerate(URLS, 1):
        # URL ohne Credentials für Anzeige
        display_url = url
        sys.stdout.write(f"[{i:2d}/{len(URLS)}] {display_url} ... ")
        sys.stdout.flush()

        result = probe_url(url)
        if result:
            # Codec + Auflösung extrahieren
            import json
            data = json.loads(result)
            streams = data.get('streams', [])
            info_parts = []
            for s in streams:
                ct = s.get('codec_type', '?')
                cn = s.get('codec_name', '?')
                if ct == 'video':
                    w = s.get('width', '?')
                    h = s.get('height', '?')
                    info_parts.append(f"Video: {cn} {w}x{h}")
                elif ct == 'audio':
                    info_parts.append(f"Audio: {cn}")
            info = ', '.join(info_parts)
            print(f"✓ {info}")
            found.append((url, info))
        else:
            print("✗")

    print(f"\n{'='*70}")
    if found:
        print(f"\n{len(found)} funktionierende Stream(s) gefunden:\n")
        for url, info in found:
            print(f"  {url}")
            print(f"    → {info}\n")
    else:
        print("\nKeine funktionierenden Streams gefunden!")


if __name__ == '__main__':
    main()
