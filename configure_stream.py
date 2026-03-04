#!/usr/bin/env python3
"""
Stream-Konfiguration der Kamera auslesen und ändern.
Ziel: Sub-Stream FPS von 5 auf 25 erhöhen.
"""

import sys
sys.path.insert(0, '.')

from onvif import ONVIFCamera
from config.config import CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD

print(f"Verbinde mit {CAMERA_IP}:{CAMERA_PORT} ...", flush=True)
cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
media = cam.create_media_service()

profiles = media.GetProfiles()

for p in profiles:
    vec = p.VideoEncoderConfiguration
    if vec is None:
        print(f"\n{p.Name}: Kein VideoEncoderConfiguration")
        continue

    res = vec.Resolution
    enc = vec.Encoding if hasattr(vec, 'Encoding') else '?'
    fps = '?'
    bitrate = '?'
    gov = '?'

    if hasattr(vec, 'RateControl') and vec.RateControl:
        fps = vec.RateControl.FrameRateLimit
        bitrate = vec.RateControl.BitrateLimit

    if hasattr(vec, 'GovLength'):
        gov = vec.GovLength

    print(f"\n{'='*60}")
    print(f"Profil: {p.Name}")
    print(f"  Token:      {vec.token}")
    print(f"  Encoding:   {enc}")
    print(f"  Auflösung:  {res.Width}x{res.Height}")
    print(f"  FPS:        {fps}")
    print(f"  Bitrate:    {bitrate} kbps")
    print(f"  GOP-Länge:  {gov}")

    # H264/H265 spezifische Config
    for codec_name in ['H264', 'H265', 'HEVC']:
        cfg = getattr(vec, codec_name, None)
        if cfg:
            print(f"  {codec_name}-Config: {cfg}")

print()
print("=" * 60)
print("Sub-Stream FPS ändern")
print("=" * 60)

# Sub-Stream Profil finden
sub_profile = None
sub_vec = None
for p in profiles:
    if 'sub' in p.Name.lower():
        sub_profile = p
        sub_vec = p.VideoEncoderConfiguration
        break

if not sub_vec:
    print("FEHLER: Kein Sub-Stream-Profil gefunden!")
    sys.exit(1)

current_fps = sub_vec.RateControl.FrameRateLimit if sub_vec.RateControl else '?'
print(f"Aktuell: {current_fps} FPS")

# Optionen abfragen
try:
    opts = media.GetVideoEncoderConfigurationOptions({'ProfileToken': sub_profile.token})
    if opts:
        print(f"\nKamera-Optionen:")
        # Suche nach FPS-Limits
        for codec_name in ['H264', 'H265', 'HEVC']:
            codec_opts = getattr(opts, codec_name, None)
            if codec_opts:
                print(f"  {codec_name}: {codec_opts}")
        if hasattr(opts, 'QualityRange'):
            print(f"  QualityRange: {opts.QualityRange}")
        # Extension
        if hasattr(opts, 'Extension') and opts.Extension:
            print(f"  Extension: {opts.Extension}")
except Exception as e:
    print(f"  Optionen-Abfrage fehlgeschlagen: {e}")

# FPS setzen
target_fps = 25
print(f"\nSetze Sub-Stream auf {target_fps} FPS...")

try:
    # Vollständige Config holen (inkl. Multicast!)
    full_vec = media.GetVideoEncoderConfiguration({'ConfigurationToken': sub_vec.token})

    # Debug: zeige was die Kamera zurückgibt
    print(f"\n  Vollständige Config:")
    for attr in dir(full_vec):
        if not attr.startswith('_'):
            val = getattr(full_vec, attr, None)
            if val is not None and not callable(val):
                print(f"    {attr}: {val}")
    print()

    full_vec.RateControl.FrameRateLimit = target_fps
    full_vec.RateControl.BitrateLimit = 512  # 512 kbps

    # Multicast muss vorhanden sein — falls nicht, Dummy setzen
    if not hasattr(full_vec, 'Multicast') or full_vec.Multicast is None:
        full_vec.Multicast = {
            'Address': {'Type': 'IPv4', 'IPv4Address': '0.0.0.0'},
            'Port': 0,
            'TTL': 0,
            'AutoStart': False,
        }

    # SessionTimeout muss vorhanden sein
    if not hasattr(full_vec, 'SessionTimeout') or full_vec.SessionTimeout is None:
        full_vec.SessionTimeout = 'PT60S'  # ISO 8601 Duration: 60 Sekunden

    media.SetVideoEncoderConfiguration({
        'Configuration': full_vec,
        'ForcePersistence': True
    })
    print(f"  ✓ ERFOLG! Sub-Stream auf {target_fps} FPS / 512kbps gesetzt!")
except Exception as e:
    print(f"  ✗ FEHLER: {e}")
    print()
    # Fallback: verschiedene FPS probieren
    for try_fps in [20, 15, 10]:
        try:
            print(f"  Versuche {try_fps} FPS...")
            full_vec.RateControl.FrameRateLimit = try_fps
            media.SetVideoEncoderConfiguration({
                'Configuration': full_vec,
                'ForcePersistence': True
            })
            print(f"  ✓ ERFOLG! Sub-Stream auf {try_fps} FPS gesetzt!")
            target_fps = try_fps
            break
        except Exception as e2:
            print(f"  ✗ {try_fps} FPS auch fehlgeschlagen: {e2}")

# Verifizieren
print("\nVerifiziere...")
profiles2 = media.GetProfiles()
for p in profiles2:
    if 'sub' in p.Name.lower():
        vec2 = p.VideoEncoderConfiguration
        new_fps = vec2.RateControl.FrameRateLimit if vec2.RateControl else '?'
        new_br = vec2.RateControl.BitrateLimit if vec2.RateControl else '?'
        print(f"  Sub-Stream jetzt: {new_fps} FPS, {new_br} kbps")
        break

print("\nFertig. App neu starten um neuen Stream zu nutzen.")
