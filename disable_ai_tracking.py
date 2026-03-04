#!/usr/bin/env python3
"""
Diagnose & Deaktivierung des KI-Trackings der Hiseeu HD118-PZ
==============================================================
Dieses Script versucht systematisch alle bekannten Wege, das
automatische Personen-/Objekt-Tracking der Kamera zu deaktivieren.

Nutzung:
    python3 disable_ai_tracking.py

Falls keiner der automatischen Wege funktioniert, wird eine
Anleitung für die manuelle Deaktivierung im Webinterface ausgegeben.
"""

import sys
import json
import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from onvif import ONVIFCamera

# --- Konfiguration ---
CAMERA_IP = '192.168.178.122'
CAMERA_PORT = 8899
USERNAME = 'admin'
PASSWORD = ''

# ============================================================
# 1. Kamera-Info über ONVIF abfragen
# ============================================================
def get_camera_info():
    print("=" * 60)
    print("1. Kamera-Informationen über ONVIF")
    print("=" * 60)
    try:
        cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
        device_service = cam.create_devicemgmt_service()
        info = device_service.GetDeviceInformation()
        print(f"  Hersteller:   {info.Manufacturer}")
        print(f"  Modell:       {info.Model}")
        print(f"  Firmware:     {info.FirmwareVersion}")
        print(f"  Seriennummer: {info.SerialNumber}")
        print(f"  Hardware:     {info.HardwareId}")
        return cam
    except Exception as e:
        print(f"  ✗ ONVIF-Verbindung fehlgeschlagen: {e}")
        return None

# ============================================================
# 2. ONVIF Analytics erkunden
# ============================================================
def explore_onvif_analytics(cam):
    print()
    print("=" * 60)
    print("2. ONVIF Analytics-Dienste erkunden")
    print("=" * 60)
    try:
        analytics = cam.create_analytics_service()
        print("  ✓ Analytics-Service verfügbar")

        try:
            configs = analytics.GetAnalyticsEngineConfigs()
            print(f"  Analytics-Engine Configs: {len(configs)}")
            for i, cfg in enumerate(configs):
                print(f"    [{i}] Token: {cfg.token}, Name: {getattr(cfg, 'Name', 'N/A')}")
        except Exception as e:
            print(f"  Analytics-Engine Configs: nicht verfügbar ({e})")

        try:
            rules = analytics.GetSupportedRules({})
            print(f"  Unterstützte Rules: {rules}")
        except Exception as e:
            print(f"  Unterstützte Rules: nicht verfügbar ({e})")

    except Exception as e:
        print(f"  ✗ Analytics-Service nicht verfügbar: {e}")

# ============================================================
# 3. ONVIF PTZ-Konfiguration prüfen
# ============================================================
def explore_ptz_config(cam):
    print()
    print("=" * 60)
    print("3. ONVIF PTZ-Konfiguration")
    print("=" * 60)
    try:
        ptz = cam.create_ptz_service()
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        profile = profiles[0]

        try:
            configs = ptz.GetConfigurations()
            for cfg in configs:
                print(f"  PTZ Config: {cfg.token}")
                print(f"    DefaultPTZTimeout: {getattr(cfg, 'DefaultPTZTimeout', 'N/A')}")
        except Exception as e:
            print(f"  PTZ Configs: {e}")

        try:
            presets = ptz.GetPresets({'ProfileToken': profile.token})
            print(f"  Presets: {len(presets)}")
            for p in presets[:5]:
                print(f"    Preset: {p.Name} (Token: {p.token})")
        except Exception as e:
            print(f"  Presets: {e}")

        # Guard Tour / Auto-Patrol prüfen
        try:
            nodes = ptz.GetNodes()
            for node in nodes:
                print(f"  PTZ-Node: {node.token}")
                print(f"    Home: {getattr(node, 'HomeSupported', 'N/A')}")
                # AuxiliaryCommands können Tracking-bezogen sein
                aux = getattr(node, 'AuxiliaryCommands', None)
                if aux:
                    print(f"    AuxiliaryCommands: {aux}")
        except Exception as e:
            print(f"  PTZ-Nodes: {e}")

    except Exception as e:
        print(f"  ✗ PTZ-Service Fehler: {e}")

# ============================================================
# 4. HTTP-CGI Endpunkte scannen
# ============================================================
def scan_http_endpoints():
    print()
    print("=" * 60)
    print("4. HTTP-CGI Endpunkte scannen")
    print("=" * 60)

    base = f"http://{CAMERA_IP}"
    auth_methods = [
        ("Ohne Auth", None),
        ("Basic Auth", HTTPBasicAuth(USERNAME, PASSWORD)),
        ("Digest Auth", HTTPDigestAuth(USERNAME, PASSWORD)),
    ]

    # Bekannte Endpoints für verschiedene Kamera-Chipsets
    endpoints = {
        "Gerätinfo": [
            "/cgi-bin/param.cgi?cmd=getdeviceinfo",
            "/cgi-bin/hi3510/param.cgi?cmd=getserverinfo",
            "/cgi-bin/configManager.cgi?action=getConfig&name=General",
            "/onvif/device_service",
        ],
        "AI / Smart Detection": [
            "/cgi-bin/param.cgi?cmd=getSmartAlarm",
            "/cgi-bin/param.cgi?cmd=gethumanaliarmattr",
            "/cgi-bin/hi3510/param.cgi?cmd=gethumanaliarmattr",
            "/cgi-bin/configManager.cgi?action=getConfig&name=SmartDetect",
            "/cgi-bin/configManager.cgi?action=getConfig&name=VideoAnalyseRule",
            "/cgi-bin/configManager.cgi?action=getConfig&name=TrafficEvent",
        ],
        "Auto-Tracking": [
            "/cgi-bin/param.cgi?cmd=getAutoTrack",
            "/cgi-bin/param.cgi?cmd=getPTZAutoTrack",
            "/cgi-bin/param.cgi?cmd=getptztrack",
            "/cgi-bin/hi3510/param.cgi?cmd=getptzautotrack",
            "/cgi-bin/configManager.cgi?action=getConfig&name=PTZAutoTrack",
        ],
        "PTZ Patrol / Guard Tour": [
            "/cgi-bin/param.cgi?cmd=getptzctrl",
            "/cgi-bin/param.cgi?cmd=getGuardTour",
            "/cgi-bin/hi3510/param.cgi?cmd=getptzctrl",
        ],
        "Alarme": [
            "/cgi-bin/param.cgi?cmd=getMotionDetect",
            "/cgi-bin/param.cgi?cmd=getalarmattr",
            "/cgi-bin/hi3510/param.cgi?cmd=getalarmattr",
        ],
    }

    # Finde erstmal die richtige Auth-Methode
    working_auth = None
    for auth_name, auth in auth_methods:
        try:
            r = requests.get(f"{base}/", auth=auth, timeout=3)
            if r.status_code in (200, 401):
                if r.status_code == 200:
                    working_auth = (auth_name, auth)
                    print(f"  Auth-Methode: {auth_name}")
                    break
        except Exception:
            pass

    if working_auth is None:
        # Default zu Basic
        working_auth = ("Basic Auth", HTTPBasicAuth(USERNAME, PASSWORD))
        print(f"  Auth-Methode: Basic Auth (Fallback)")

    auth_name, auth = working_auth

    for category, urls in endpoints.items():
        print(f"\n  --- {category} ---")
        for url_path in urls:
            try:
                r = requests.get(f"{base}{url_path}", auth=auth, timeout=3)
                status = "✓" if r.status_code == 200 else f"✗ ({r.status_code})"
                print(f"  {status} {url_path}")
                if r.status_code == 200 and r.text.strip():
                    # Antwort anzeigen (gekürzt)
                    text = r.text.strip()[:300]
                    for line in text.split('\n'):
                        print(f"       {line.strip()}")
            except requests.exceptions.RequestException as e:
                print(f"  ✗ {url_path} — Timeout/Fehler")

# ============================================================
# 5. Deaktivierungsversuche
# ============================================================
def try_disable_tracking():
    print()
    print("=" * 60)
    print("5. KI-Tracking deaktivieren — Versuche")
    print("=" * 60)

    base = f"http://{CAMERA_IP}"
    auth = HTTPBasicAuth(USERNAME, PASSWORD)

    disable_cmds = [
        # Smart / AI Detection
        ("Smart Detection AUS",
         f"{base}/cgi-bin/param.cgi?cmd=setSmartAlarm&-smd_enable=0&-humanoid_enable=0"),
        ("AI Enable AUS",
         f"{base}/cgi-bin/param.cgi?cmd=setSmartAlarm&-ai_enable=0"),
        ("Humanoid Detection AUS",
         f"{base}/cgi-bin/hi3510/param.cgi?cmd=sethumanaliarmattr&-enable=0"),
        # Auto-Tracking
        ("Auto-Track AUS (param)",
         f"{base}/cgi-bin/param.cgi?cmd=setAutoTrack&-enable=0"),
        ("PTZ Auto-Track AUS",
         f"{base}/cgi-bin/param.cgi?cmd=setPTZAutoTrack&-enable=0"),
        ("PTZ Track AUS (hi3510)",
         f"{base}/cgi-bin/hi3510/param.cgi?cmd=setptzautotrack&-enable=0"),
        # Config Manager Style
        ("SmartDetect AUS (configManager)",
         f"{base}/cgi-bin/configManager.cgi?action=setConfig&SmartDetect.Enable=false"),
        ("VideoAnalyse AUS (configManager)",
         f"{base}/cgi-bin/configManager.cgi?action=setConfig&VideoAnalyseRule[0].Enable=false"),
        ("PTZAutoTrack AUS (configManager)",
         f"{base}/cgi-bin/configManager.cgi?action=setConfig&PTZAutoTrack.Enable=false"),
    ]

    success = []
    for name, url in disable_cmds:
        for auth_attempt in [HTTPBasicAuth(USERNAME, PASSWORD), HTTPDigestAuth(USERNAME, PASSWORD), None]:
            try:
                r = requests.get(url, auth=auth_attempt, timeout=3)
                if r.status_code == 200 and 'error' not in r.text.lower():
                    print(f"  ✓ {name}")
                    if r.text.strip():
                        print(f"       Antwort: {r.text.strip()[:100]}")
                    success.append(name)
                    break
                else:
                    pass
            except Exception:
                pass
        else:
            print(f"  ✗ {name}")

    return success

# ============================================================
# 6. Zusammenfassung
# ============================================================
def print_manual_instructions():
    print()
    print("=" * 60)
    print("MANUELLE DEAKTIVIERUNG (falls automatisch nicht möglich)")
    print("=" * 60)
    print(f"""
  1. Öffne im Browser: http://{CAMERA_IP}
     Login: {USERNAME} / {'(kein Passwort)' if not PASSWORD else PASSWORD}

  2. Suche in den Einstellungen nach:
     • "Smart Detection" / "Intelligente Erkennung" → AUS
     • "Auto Tracking" / "Automatische Verfolgung" → AUS
     • "Human Detection" / "Personenerkennung" → AUS
     • "Motion Tracking" / "Bewegungsverfolgung" → AUS
     • "Guard Tour" / "Patrouille" → AUS

  3. Unter "PTZ" Einstellungen:
     • "Auto Patrol" / "Automatische Patrouille" → AUS
     • "Idle Action" / "Leerlauf-Aktion" → NONE / KEINE

  4. Falls die Kamera eine Handy-App nutzt (z.B. CamHi/iCSee/XMEye):
     • App öffnen → Geräteeinstellungen → AI/Smart → Alles AUS
     • Oft lässt sich Tracking NUR über die App deaktivieren!

  5. Alternativ: Kamera auf Werkseinstellungen zurücksetzen
     (Reset-Knopf 10 Sek drücken) und dann NUR über ONVIF
     steuern, ohne die Hersteller-App einzurichten.
""")

# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    cam = get_camera_info()

    if cam:
        explore_onvif_analytics(cam)
        explore_ptz_config(cam)

    scan_http_endpoints()
    successes = try_disable_tracking()

    if successes:
        print()
        print("=" * 60)
        print(f"ERGEBNIS: {len(successes)} Deaktivierung(en) erfolgreich!")
        print("=" * 60)
        for s in successes:
            print(f"  ✓ {s}")
    else:
        print_manual_instructions()

    print()
    print("Fertig. Starte danach 'python3 main.py' um zu testen.")
