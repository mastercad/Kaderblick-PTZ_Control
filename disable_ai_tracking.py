#!/usr/bin/env python3
"""
Diagnose & Deaktivierung des KI-Trackings der Hiseeu HD118-PZ
==============================================================
Kamera-Chip: Novatek NT98566 mit XM/Xiongmai-Firmware
Protokoll:   XM JSON-RPC über HTTP POST (NICHT GET!)

Die Kamera antwortet auf GET-Requests mit:
  { "Ret":136, "Tip":"Not support GET method" }
Alle Befehle müssen als POST mit JSON-Body gesendet werden.

Nutzung:
    python3 disable_ai_tracking.py
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

CGI_URL = f"http://{CAMERA_IP}/cgi-bin/param.cgi"

# ============================================================
# XM JSON-RPC Hilfsfunktionen
# ============================================================
def xm_post(cmd, payload=None, auth=None):
    """
    Sendet einen POST-Request an die XM-Kamera im JSON-RPC-Format.
    Gibt (erfolg: bool, antwort: dict|str) zurück.
    """
    data = {"cmd": cmd}
    if payload is not None:
        data.update(payload)

    try:
        r = requests.post(CGI_URL, json=data, auth=auth, timeout=5)
    except requests.exceptions.RequestException as e:
        return False, f"Verbindungsfehler: {e}"

    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"

    text = r.text.strip()

    # Prüfe auf bekannte Fehlermeldungen
    if "Not support" in text:
        return False, f"Nicht unterstützt: {text[:100]}"

    # Versuche JSON zu parsen
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Manche Antworten kommen als rohes Key=Value
        return True, text[:200] if text else "(leere Antwort)"

    # XM-Kameras nutzen "Ret" als Return-Code
    # Ret 0 oder 100 = Erfolg, alles andere = Fehler
    ret = result.get("Ret", None)
    if ret is not None:
        if ret in (0, 100):
            return True, result
        else:
            tip = result.get("Tip", "")
            return False, f"Ret={ret} Tip={tip}"

    # Wenn kein "Ret"-Feld, dann ist es wahrscheinlich eine Daten-Antwort
    return True, result


def xm_get_config(cmd, auth=None):
    """Liest eine Konfiguration per POST ab."""
    return xm_post(cmd, auth=auth)


def xm_set_config(cmd, params, auth=None):
    """Setzt eine Konfiguration per POST."""
    return xm_post(cmd, payload=params, auth=auth)


# ============================================================
# 1. Kamera-Info über ONVIF
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
# 3. PTZ-Konfiguration prüfen
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

        try:
            nodes = ptz.GetNodes()
            for node in nodes:
                print(f"  PTZ-Node: {node.token}")
                print(f"    Home: {getattr(node, 'HomeSupported', 'N/A')}")
                aux = getattr(node, 'AuxiliaryCommands', None)
                if aux:
                    print(f"    AuxiliaryCommands: {aux}")
        except Exception as e:
            print(f"  PTZ-Nodes: {e}")

    except Exception as e:
        print(f"  ✗ PTZ-Service Fehler: {e}")


# ============================================================
# 4. XM JSON-RPC Konfigurationen auslesen (POST!)
# ============================================================
def scan_xm_configs():
    print()
    print("=" * 60)
    print("4. XM-Kamera Konfigurationen auslesen (POST JSON-RPC)")
    print("=" * 60)

    # Bekannte GET-Befehle im XM-Protokoll (per POST gesendet!)
    get_commands = {
        "Geräte-Info": [
            "getDeviceInfo",
            "getServerInfo",
            "getSystemInfo",
        ],
        "AI / Smart Detection": [
            "getSmartAlarm",
            "getHumanDetection",
            "getHumanAlarm",
            "gethumanaliarmattr",
            "getSmartDetectCfg",
            "getAiDetectConfig",
            "getIntelliTraceConfig",
        ],
        "Auto-Tracking / PTZ": [
            "getAutoTrack",
            "getPTZAutoTrack",
            "getptztrack",
            "getPTZTrackConfig",
            "getGuardTour",
            "getptzctrl",
        ],
        "Alarme / Motion": [
            "getMotionDetect",
            "getalarmattr",
            "getAlarmConfig",
        ],
    }

    found_configs = {}

    for category, cmds in get_commands.items():
        print(f"\n  --- {category} ---")
        for cmd in cmds:
            # Versuche ohne und mit Auth
            for auth in [None, HTTPBasicAuth(USERNAME, PASSWORD),
                         HTTPDigestAuth(USERNAME, PASSWORD)]:
                ok, result = xm_get_config(cmd, auth=auth)
                if ok:
                    print(f"  ✓ {cmd}")
                    if isinstance(result, dict):
                        for k, v in result.items():
                            if k not in ("Ret", "SessionID"):
                                print(f"       {k}: {json.dumps(v, indent=2) if isinstance(v, (dict, list)) else v}")
                                found_configs[cmd] = result
                    else:
                        print(f"       {result}")
                        found_configs[cmd] = result
                    break  # Auth gefunden, weiter zum nächsten Befehl
                else:
                    if "Nicht unterstützt" in str(result):
                        # POST ging durch, aber Befehl nicht unterstützt
                        continue
                    if "Verbindungsfehler" in str(result):
                        break  # Kamera nicht erreichbar
            else:
                # Kein Auth hat funktioniert oder Befehl nicht unterstützt
                print(f"  ✗ {cmd} — {result}")

    return found_configs


# ============================================================
# 5. KI-Tracking deaktivieren (POST JSON-RPC!)
# ============================================================
def try_disable_tracking(found_configs):
    print()
    print("=" * 60)
    print("5. KI-Tracking deaktivieren (POST JSON-RPC)")
    print("=" * 60)

    # Alle Disable-Befehle mit verschiedenen Parameternamen,
    # da XM-Firmware-Versionen unterschiedliche Namen nutzen
    disable_commands = [
        # --- Smart / AI / Humanoid Detection ---
        ("Smart Alarm AUS", "setSmartAlarm", {
            "SmartAlarm": {"Enable": False, "HumanoidEnable": False,
                           "SmdEnable": False, "AiEnable": False}
        }),
        ("Smart Alarm (flat)", "setSmartAlarm", {
            "smd_enable": 0, "humanoid_enable": 0, "ai_enable": 0
        }),
        ("Human Detection AUS", "setHumanDetection", {
            "HumanDetection": {"Enable": False}
        }),
        ("Human Alarm AUS", "setHumanAlarm", {
            "HumanAlarm": {"Enable": False}
        }),
        ("Humanoid Alarm AUS", "sethumanaliarmattr", {
            "enable": 0
        }),
        ("Smart Detect Config AUS", "setSmartDetectCfg", {
            "SmartDetectCfg": {"Enable": False, "ObjectTypes": []}
        }),
        ("AI Detect AUS", "setAiDetectConfig", {
            "AiDetectConfig": {"Enable": False}
        }),

        # --- Auto-Tracking / PTZ Tracking ---
        ("Auto-Track AUS", "setAutoTrack", {
            "AutoTrack": {"Enable": False}
        }),
        ("Auto-Track (flat)", "setAutoTrack", {
            "enable": 0
        }),
        ("PTZ Auto-Track AUS", "setPTZAutoTrack", {
            "PTZAutoTrack": {"Enable": False}
        }),
        ("PTZ Track Config AUS", "setPTZTrackConfig", {
            "PTZTrackConfig": {"Enable": False}
        }),
        ("PTZ Track (flat)", "setptztrack", {
            "enable": 0
        }),
        ("Intelli-Trace AUS", "setIntelliTraceConfig", {
            "IntelliTraceConfig": {"Enable": False}
        }),

        # --- Guard Tour / Patrol ---
        ("Guard Tour AUS", "setGuardTour", {
            "GuardTour": {"Enable": False}
        }),
    ]

    success = []
    failed = []

    for name, cmd, params in disable_commands:
        # Versuche ohne und mit Auth
        best_result = None
        for auth in [None, HTTPBasicAuth(USERNAME, PASSWORD),
                     HTTPDigestAuth(USERNAME, PASSWORD)]:
            ok, result = xm_set_config(cmd, params, auth=auth)
            if ok:
                print(f"  ✓ {name}")
                if isinstance(result, dict):
                    print(f"       Antwort: {json.dumps(result)[:120]}")
                else:
                    print(f"       Antwort: {str(result)[:120]}")
                success.append(name)
                break
            best_result = result
        else:
            # Nur als Fehler zeigen wenn mindestens einer es versucht hat
            print(f"  ✗ {name} — {best_result}")
            failed.append(name)

    return success, failed


# ============================================================
# 6. Zusammenfassung & manuelle Anleitung
# ============================================================
def print_manual_instructions():
    print(f"""
  ╔══════════════════════════════════════════════════════════╗
  ║  MANUELLE DEAKTIVIERUNG                                 ║
  ║  (falls automatisch nicht möglich)                      ║
  ╚══════════════════════════════════════════════════════════╝

  Die Kamera (XM/Xiongmai NT98566) hat proprietäre AI-Features,
  die sich möglicherweise NUR über die Hersteller-App deaktivieren
  lassen.

  Option 1 — Handy-App (wahrscheinlichste Lösung):
    • Installiere "iCSee" oder "XMEye" auf dem Handy
    • Kamera hinzufügen: {CAMERA_IP}
    • Einstellungen → Smart/AI Detection → ALLES AUS
    • Einstellungen → Tracking/Verfolgung → AUS

  Option 2 — Webinterface:
    • Öffne http://{CAMERA_IP} im Browser
    • Login: {USERNAME} / {'(kein Passwort)' if not PASSWORD else PASSWORD}
    • Suche nach: Smart Detection / Auto Tracking / Human → AUS

  Option 3 — Werksreset:
    • Reset-Knopf an der Kamera 10 Sek gedrückt halten
    • Kamera NUR über ONVIF einrichten (nicht über App)
    • So werden keine AI-Features aktiviert

  Option 4 — Netzwerk-Isolation:
    • Kamera vom Internet trennen (nur lokales Netz)
    • Manche AI-Features brauchen Cloud-Verbindung
""")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    cam = get_camera_info()

    if cam:
        explore_onvif_analytics(cam)
        explore_ptz_config(cam)

    found = scan_xm_configs()
    success, failed = try_disable_tracking(found)

    print()
    print("=" * 60)
    if success:
        print(f"ERGEBNIS: {len(success)} Deaktivierung(en) tatsächlich erfolgreich")
        print("=" * 60)
        for s in success:
            print(f"  ✓ {s}")
        if failed:
            print(f"\n  ({len(failed)} Befehle nicht unterstützt — ist normal,")
            print(f"   verschiedene Firmware-Versionen nutzen verschiedene Namen)")
    else:
        print("ERGEBNIS: Kein automatischer Deaktivierungs-Befehl war erfolgreich")
        print("=" * 60)
        print_manual_instructions()

    print()
    print("Fertig. Starte danach 'python3 main.py' um zu testen.")
