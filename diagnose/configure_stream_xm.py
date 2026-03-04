#!/usr/bin/env python3
"""
Sub-Stream FPS über XM/DVRIP-Protokoll ändern (Port 34567).
ONVIF verweigert SetVideoEncoderConfiguration auf dieser Kamera.

Strategie: Aktuelle Config lesen, FPS-Feld ändern, zurückschreiben.
"""

import json
import sys

sys.path.insert(0, '.')
from src import xm_protocol as xm

TARGET_FPS = 25

# ── Verbindung ────────────────────────────────────────────────
print("Verbinde über XM/DVRIP (Port 34567)...", flush=True)
sock, session_id = xm.connect_and_login()
if sock is None:
    print("FEHLER: XM-Verbindung fehlgeschlagen!")
    sys.exit(1)
print(f"  Verbunden. Session: 0x{session_id:08X}\n")


# ── Alle Encode-Configs scannen ───────────────────────────────
print("=" * 60)
print("Encode-Konfigurations-Scan")
print("=" * 60)

config_names = [
    "Simplify.Encode",
    "AVEnc.Encode",
    "AVEnc.EncodeStaticParam",
    "AVEnc.SmartH264V2",
    "Encode",
    "Camera.Param",
    "fVideo.EncodeParam",
]

found = {}
for name in config_names:
    ok, data = xm.get_config(sock, session_id, name)
    if ok and data:
        found[name] = data
        print(f"\n  ✓ {name}:")
        for key, val in data.items():
            if key not in ("Name", "Ret", "SessionID"):
                print(f"    {key}: {json.dumps(val, indent=6)}")
    else:
        print(f"  ✗ {name}: nicht verfügbar")

if not found:
    print("\nKeine Encode-Konfiguration gefunden!")
    sock.close()
    sys.exit(1)


# ── Sub-Stream FPS aus gelesener Config ändern ────────────────
print()
print("=" * 60)
print(f"Sub-Stream auf {TARGET_FPS} FPS setzen")
print("=" * 60)

success = False

# Methode 1: Simplify.Encode — häufigstes Format
if "Simplify.Encode" in found:
    cfg_name = "Simplify.Encode"
    raw = found[cfg_name]
    cfg_list = raw.get(cfg_name)

    if isinstance(cfg_list, list) and len(cfg_list) > 0:
        entry = cfg_list[0]
        extra = entry.get("ExtraFormat", {})
        video = extra.get("Video", {})
        old_fps = video.get("FPS", "?")
        print(f"\n  Simplify.Encode[0].ExtraFormat.Video.FPS: {old_fps}")

        # FPS ändern
        video["FPS"] = TARGET_FPS
        extra["Video"] = video
        entry["ExtraFormat"] = extra
        cfg_list[0] = entry

        print(f"  Setze auf {TARGET_FPS} FPS...")
        print(f"  Sende: {json.dumps(cfg_list[0]['ExtraFormat']['Video'], indent=4)}")

        ok = xm.set_config(sock, session_id, cfg_name, cfg_list)
        if ok:
            print(f"  ✓ ERFOLG!")
            success = True
        else:
            print(f"  ✗ Abgelehnt")

# Methode 2: AVEnc.Encode — alternatives Format
if not success and "AVEnc.Encode" in found:
    cfg_name = "AVEnc.Encode"
    raw = found[cfg_name]
    cfg_list = raw.get(cfg_name)

    if isinstance(cfg_list, list) and len(cfg_list) > 0:
        entry = cfg_list[0]
        extra = entry.get("ExtraFormat", entry.get("Extra", {}))
        video = extra.get("Video", {})
        old_fps = video.get("FPS", "?")
        print(f"\n  AVEnc.Encode[0].ExtraFormat.Video.FPS: {old_fps}")

        video["FPS"] = TARGET_FPS
        extra["Video"] = video
        if "ExtraFormat" in entry:
            entry["ExtraFormat"] = extra
        else:
            entry["Extra"] = extra
        cfg_list[0] = entry

        print(f"  Setze auf {TARGET_FPS} FPS...")
        ok = xm.set_config(sock, session_id, cfg_name, cfg_list)
        if ok:
            print(f"  ✓ ERFOLG!")
            success = True
        else:
            print(f"  ✗ Abgelehnt")

# Methode 3: Falls Config anders strukturiert — Fallback-Versuche
if not success:
    print("\n  Standard-Methoden fehlgeschlagen. Versuche alternative Strukturen...")

    alternatives = [
        ("Simplify.Encode", [{"ExtraFormat": {"Video": {"FPS": TARGET_FPS}}}]),
        ("AVEnc.Encode", [{"ExtraFormat": {"Video": {"FPS": TARGET_FPS}}}]),
        ("Simplify.Encode", {"ExtraFormat": {"Video": {"FPS": TARGET_FPS}}}),
        ("AVEnc.Encode", {"ExtraFormat": {"Video": {"FPS": TARGET_FPS}}}),
    ]

    for cfg_name, cfg_data in alternatives:
        print(f"  Versuche {cfg_name} mit {type(cfg_data).__name__}...")
        ok = xm.set_config(sock, session_id, cfg_name, cfg_data)
        if ok:
            print(f"  ✓ ERFOLG mit {cfg_name}!")
            success = True
            break
        else:
            print(f"  ✗ Abgelehnt")


# ── Verifizieren ──────────────────────────────────────────────
print()
print("=" * 60)
print("Verifizierung")
print("=" * 60)

for name in ["Simplify.Encode", "AVEnc.Encode"]:
    ok, data = xm.get_config(sock, session_id, name)
    if ok and data:
        cfg_list = data.get(name, [])
        if isinstance(cfg_list, list) and len(cfg_list) > 0:
            extra = cfg_list[0].get("ExtraFormat", {})
            video = extra.get("Video", {})
            fps = video.get("FPS", "?")
            print(f"  {name} Sub-Stream FPS: {fps}")
        break

sock.close()

if success:
    print("\n✓ Fertig. App neu starten um neuen Stream zu nutzen.")
else:
    print("\n✗ FPS-Änderung fehlgeschlagen.")
    print("  Mögliche Alternativen:")
    print("  - FPS über das Web-Interface der Kamera ändern (http://192.168.178.122)")
    print("  - Hauptstream statt Sub-Stream nutzen (höhere Auflösung, mehr FPS)")
