#!/usr/bin/env python3
"""
Diagnose & Deaktivierung des KI-Trackings der Hiseeu HD118-PZ
==============================================================
Kamera-Chip: Novatek NT98566 mit XM/Xiongmai-Firmware

Die HTTP-Schnittstelle (Port 80) unterstützt KEINE Konfigurationsänderungen
(weder GET noch POST → "Not support this POST method").

Stattdessen nutzt dieses Skript das XM Binary Protocol auf Port 34567,
das nachweislich funktioniert (Login + PTZ bestätigt).

Nutzung:
    python3 disable_ai_tracking.py
"""

import sys
import socket
import struct
import json
import hashlib
import time
from onvif import ONVIFCamera

# --- Konfiguration ---
CAMERA_IP = '192.168.178.122'
ONVIF_PORT = 8899
XM_PORT = 34567
USERNAME = 'admin'
PASSWORD = ''

# XM-Protokoll Konstanten
XM_HEADER = 0xFF

# Message-IDs
LOGIN_REQ = 1000
LOGIN_RSP = 1001
CONFIG_GET = 1042       # Konfiguration lesen
CONFIG_GET_RSP = 1043
CONFIG_SET = 1040       # Konfiguration schreiben
CONFIG_SET_RSP = 1041
SYSINFO_REQ = 1020
SYSINFO_RSP = 1021
ABILITY_GET = 1360      # Fähigkeiten des Geräts abfragen
ABILITY_GET_RSP = 1361
OPMONITOR_REQ = 1413    # OPMonitor (manches Tracking)
SYSMANAGER_REQ = 1450   # System-Manager Befehle


# ============================================================
# XM Binary Protocol Hilfsfunktionen
# ============================================================
def xm_hash_password(password):
    """XM-Kameras nutzen ein spezielles Password-Hashing."""
    m = hashlib.md5(password.encode('utf-8') if password else b"").digest()
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    result = ""
    for i in range(8):
        idx = m[2 * i] + m[2 * i + 1]
        result += chars[idx % len(chars)]
    return result


def build_xm_packet(msg_id, session_id, data_bytes):
    """Baut ein XM/DVRIP-Protokoll-Paket (20 Byte Header + Daten)."""
    header = struct.pack(
        '<BBBB I I BB H I',
        XM_HEADER, 0x00, 0x00, 0x00,
        session_id, 0,
        0, 0,
        msg_id,
        len(data_bytes),
    )
    return header + data_bytes


def parse_xm_response(sock, timeout=5):
    """Empfängt und parst eine XM/DVRIP-Antwort."""
    sock.settimeout(timeout)
    try:
        header = b''
        while len(header) < 20:
            chunk = sock.recv(20 - len(header))
            if not chunk:
                return None, None, "Verbindung geschlossen"
            header += chunk

        (head_flag, version, res1, res2,
         session_id, seq,
         total_pkts, cur_pkt,
         msg_id, data_len) = struct.unpack('<BBBB I I BB H I', header)

        if head_flag != XM_HEADER:
            return msg_id, session_id, f"Ungültiger Header: {head_flag:#04x}"

        data = b''
        while len(data) < data_len:
            chunk = sock.recv(min(data_len - len(data), 4096))
            if not chunk:
                break
            data += chunk

        data_str = data.rstrip(b'\x00\x0a').decode('utf-8', errors='replace')
        try:
            result = json.loads(data_str)
        except json.JSONDecodeError:
            result = data_str

        return msg_id, session_id, result

    except socket.timeout:
        return None, None, "Timeout"
    except Exception as e:
        return None, None, str(e)


def xm_login(sock):
    """Login über XM Binary Protocol. Gibt session_id zurück oder None."""
    hashed_pw = xm_hash_password(PASSWORD)
    login_data = json.dumps({
        "EncryptType": "MD5",
        "LoginType": "DVRIP-Web",
        "PassWord": hashed_pw,
        "UserName": USERNAME
    }).encode('utf-8') + b'\x0a'

    packet = build_xm_packet(LOGIN_REQ, 0, login_data)
    sock.sendall(packet)

    msg_id, session_id, result = parse_xm_response(sock, timeout=5)

    if isinstance(result, dict) and result.get("Ret") == 100:
        session = result.get("SessionID", session_id)
        if isinstance(session, str):
            session = int(session, 16) if session.startswith("0x") else int(session)
        return session
    return None


def xm_get_config(sock, session_id, config_name):
    """
    Liest eine Konfiguration über XM Binary Protocol.
    Gibt (erfolg, ergebnis) zurück.
    """
    payload = json.dumps({
        "Name": config_name,
        "SessionID": f"0x{session_id:08X}"
    }).encode('utf-8') + b'\x0a'

    packet = build_xm_packet(CONFIG_GET, session_id, payload)
    sock.sendall(packet)
    msg_id, _, result = parse_xm_response(sock, timeout=3)

    if msg_id is None:
        return False, result  # Timeout/Fehler

    if isinstance(result, dict):
        ret = result.get("Ret", -1)
        if ret in (100, 0):
            return True, result
        else:
            return False, result
    return False, result


def xm_set_config(sock, session_id, config_name, config_data):
    """
    Setzt eine Konfiguration über XM Binary Protocol.
    Gibt (erfolg, ergebnis) zurück.
    """
    payload_dict = {
        "Name": config_name,
        config_name: config_data,
        "SessionID": f"0x{session_id:08X}"
    }
    payload = json.dumps(payload_dict).encode('utf-8') + b'\x0a'

    packet = build_xm_packet(CONFIG_SET, session_id, payload)
    sock.sendall(packet)
    msg_id, _, result = parse_xm_response(sock, timeout=3)

    if msg_id is None:
        return False, result

    if isinstance(result, dict):
        ret = result.get("Ret", -1)
        if ret in (100, 0):
            return True, result
        else:
            return False, result
    return False, result


def xm_get_ability(sock, session_id, ability_name):
    """Fragt eine Geräte-Fähigkeit ab (msg_id 1360)."""
    payload = json.dumps({
        "Name": ability_name,
        "SessionID": f"0x{session_id:08X}"
    }).encode('utf-8') + b'\x0a'

    packet = build_xm_packet(ABILITY_GET, session_id, payload)
    sock.sendall(packet)
    msg_id, _, result = parse_xm_response(sock, timeout=3)

    if msg_id is None:
        return False, result

    if isinstance(result, dict):
        ret = result.get("Ret", -1)
        if ret in (100, 0):
            return True, result
        else:
            return False, result
    return False, result


# ============================================================
# 1. Kamera-Info über ONVIF
# ============================================================
def get_camera_info():
    print("=" * 60)
    print("1. Kamera-Informationen über ONVIF")
    print("=" * 60)
    try:
        cam = ONVIFCamera(CAMERA_IP, ONVIF_PORT, USERNAME, PASSWORD)
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
# 2. XM Binary Protocol — Verbinden & Login
# ============================================================
def xm_connect_and_login():
    print()
    print("=" * 60)
    print("2. XM Binary Protocol — Login (Port 34567)")
    print("=" * 60)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((CAMERA_IP, XM_PORT))
        print(f"  ✓ Verbunden mit {CAMERA_IP}:{XM_PORT}")
    except Exception as e:
        print(f"  ✗ Verbindung fehlgeschlagen: {e}")
        return None, None

    session_id = xm_login(sock)
    if session_id is not None:
        print(f"  ✓ Login erfolgreich — SessionID: {session_id:#010x}")
        return sock, session_id
    else:
        print(f"  ✗ Login fehlgeschlagen")
        sock.close()
        return None, None


# ============================================================
# 3. System-Infos & Fähigkeiten abfragen
# ============================================================
def scan_system_info(sock, session_id):
    print()
    print("=" * 60)
    print("3. System-Informationen & Fähigkeiten (XM Binary)")
    print("=" * 60)

    # SystemInfo abfragen
    print("\n  --- SystemInfo ---")
    payload = json.dumps({
        "Name": "SystemInfo",
        "SessionID": f"0x{session_id:08X}"
    }).encode('utf-8') + b'\x0a'
    packet = build_xm_packet(SYSINFO_REQ, session_id, payload)
    sock.sendall(packet)
    msg_id, _, result = parse_xm_response(sock, timeout=3)
    if isinstance(result, dict) and result.get("Ret") in (100, 0):
        si = result.get("SystemInfo", result)
        for k, v in (si.items() if isinstance(si, dict) else []):
            if k not in ("Ret", "SessionID", "Name"):
                print(f"  {k}: {v}")
    else:
        print(f"  SystemInfo: {_fmt_result(result)}")

    # Fähigkeiten abfragen — speziell nach AI/Smart/Tracking
    print("\n  --- Geräte-Fähigkeiten ---")
    ability_names = [
        "SystemFunction",
        "OPSystemFunction",
    ]
    for ability in ability_names:
        ok, result = xm_get_ability(sock, session_id, ability)
        if ok:
            print(f"  ✓ {ability}:")
            if isinstance(result, dict):
                _print_relevant_keys(result, indent=6)
            else:
                print(f"      {str(result)[:200]}")
        else:
            print(f"  ✗ {ability}: {_fmt_result(result)}")


def _fmt_result(result):
    """Formatiert ein Ergebnis kompakt für die Ausgabe."""
    if isinstance(result, dict):
        ret = result.get("Ret", "?")
        name = result.get("Name", "")
        return f"Ret={ret}" + (f" Name={name}" if name else "")
    return str(result)[:120]


def _print_relevant_keys(d, indent=4, max_depth=3, _depth=0):
    """Gibt relevante Schlüssel eines Dicts aus (AI/Track/Smart/Human)."""
    if _depth > max_depth:
        return
    prefix = " " * indent
    keywords = ["ai", "smart", "track", "human", "detect", "intelli",
                 "alarm", "ptz", "guard", "patrol", "cruise", "tour",
                 "motion", "smd", "follow"]

    for key, val in d.items():
        if key in ("Ret", "SessionID", "Name"):
            continue
        key_lower = key.lower()
        is_relevant = any(kw in key_lower for kw in keywords)

        if isinstance(val, dict):
            if is_relevant or _depth < 1:
                print(f"{prefix}{key}:")
                _print_relevant_keys(val, indent + 4, max_depth, _depth + 1)
        elif isinstance(val, list) and len(val) < 20:
            if is_relevant:
                relevant_items = [
                    item for item in val
                    if isinstance(item, str) and any(kw in item.lower() for kw in keywords)
                ]
                if relevant_items:
                    print(f"{prefix}{key}: {relevant_items}")
                else:
                    print(f"{prefix}{key}: ({len(val)} Einträge)")
        else:
            if is_relevant:
                print(f"{prefix}{key}: {val}")


# ============================================================
# 4. KI/Tracking-Konfigurationen auslesen
# ============================================================
def scan_ai_configs(sock, session_id):
    print()
    print("=" * 60)
    print("4. KI/Tracking-Konfigurationen auslesen (XM Binary)")
    print("=" * 60)

    # Alle bekannten Config-Namen der XM-Plattform für AI/Tracking
    config_names = {
        "AI / Smart Detection": [
            "Detect.HumanDetection",
            "Detect.SmartDetect",
            "Detect.HumanoidDetect",
            "Detect.SmartDetectCfg",
            "NetWork.NetSmartDetect",
            "Alarm.HumanDetection",
            "Alarm.SmartAlarm",
            "Alarm.HumanAlarm",
            "fVideo.SmartDetect",
            "fVideo.HumanDetect",
        ],
        "Auto-Tracking / PTZ": [
            "Camera.PtzAutoTrack",
            "Camera.PTZAutoTrack",
            "PTZAutoTrack",
            "Ptz.AutoTracking",
            "Ptz.AutoTrack",
            "fVideo.IntelliTrace",
            "fVideo.IntelliTrack",
            "IntelliTrace",
            "IntelliTrack",
            "Camera.PtzTrack",
            "PTZTrack",
        ],
        "Guard Tour / Patrol": [
            "Camera.GuardTour",
            "Camera.GuardCruise",
            "GuardTour",
            "Tour",
            "Ptz.Tour",
        ],
        "Motion Detection": [
            "Detect.MotionDetect",
            "Alarm.MotionDetect",
        ],
        "Allgemeine Kamera-Config": [
            "Camera.Param",
            "Camera.ParamEx",
            "AVEnc.SmartH264",
            "AVEnc.SmartH265",
        ],
    }

    found_configs = {}

    for category, names in config_names.items():
        print(f"\n  --- {category} ---")
        for name in names:
            ok, result = xm_get_config(sock, session_id, name)
            if ok:
                print(f"  ✓ {name}:")
                if isinstance(result, dict):
                    config_data = result.get(name, result)
                    if isinstance(config_data, dict):
                        for k, v in config_data.items():
                            if k not in ("Ret", "SessionID", "Name"):
                                val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                                print(f"      {k}: {val_str[:100]}")
                    elif isinstance(config_data, list):
                        for i, item in enumerate(config_data[:3]):
                            print(f"      [{i}]: {json.dumps(item)[:120]}")
                        if len(config_data) > 3:
                            print(f"      ... ({len(config_data)} Einträge)")
                    else:
                        print(f"      {json.dumps(config_data)[:200]}")
                    found_configs[name] = result
                else:
                    print(f"      {str(result)[:200]}")
                    found_configs[name] = result
            else:
                ret = result.get("Ret", "?") if isinstance(result, dict) else "?"
                if ret == 104:
                    print(f"  🔒 {name} — Kein Zugriff (Ret=104)")
                elif isinstance(result, str) and "Timeout" in result:
                    print(f"  ⏱ {name} — Timeout")
                # Ret 102 = nicht vorhanden → still ignorieren

    return found_configs


# ============================================================
# 5. KI-Tracking deaktivieren
# ============================================================
def try_disable_tracking(sock, session_id, found_configs):
    print()
    print("=" * 60)
    print("5. KI-Tracking deaktivieren (XM Binary Protocol)")
    print("=" * 60)

    success = []
    failed = []

    # ---- Strategie 1: Gefundene Konfigurationen direkt ändern ----
    if found_configs:
        print("\n  --- Gefundene Configs deaktivieren ---")
        for config_name, current_config in found_configs.items():
            config_data = current_config.get(config_name, current_config)
            if isinstance(config_data, dict):
                disabled = _disable_config(config_data)
                ok, result = xm_set_config(sock, session_id, config_name, disabled)
                if ok:
                    print(f"  ✓ {config_name} → DEAKTIVIERT")
                    success.append(config_name)
                else:
                    print(f"  ✗ {config_name} → {_fmt_result(result)}")
                    failed.append(config_name)
            elif isinstance(config_data, list) and len(config_data) > 0:
                disabled = [_disable_config(item) if isinstance(item, dict) else item
                            for item in config_data]
                ok, result = xm_set_config(sock, session_id, config_name, disabled)
                if ok:
                    print(f"  ✓ {config_name} → DEAKTIVIERT (Array)")
                    success.append(config_name)
                else:
                    print(f"  ✗ {config_name} → {_fmt_result(result)}")
                    failed.append(config_name)

    # ---- Strategie 2: Blinde Disable-Befehle ----
    print("\n  --- Blinde Disable-Befehle ---")

    blind_disables = [
        # AI Detection
        ("Detect.HumanDetection", {"Enable": False}),
        ("Detect.HumanDetection", [{"Enable": False}]),
        ("Detect.SmartDetect", {"Enable": False}),
        ("Detect.HumanoidDetect", {"Enable": False, "ObjectType": 0}),
        ("Alarm.SmartAlarm", {"Enable": False, "HumanoidEnable": False,
                               "SmdEnable": False, "AiEnable": False}),
        ("Alarm.HumanAlarm", {"Enable": False}),
        ("Alarm.HumanDetection", {"Enable": False}),
        ("fVideo.SmartDetect", {"Enable": False}),
        ("NetWork.NetSmartDetect", {"Enable": False}),

        # Auto-Tracking
        ("Camera.PtzAutoTrack", {"Enable": False}),
        ("Camera.PTZAutoTrack", {"Enable": False}),
        ("PTZAutoTrack", {"Enable": False}),
        ("Ptz.AutoTracking", {"Enable": False}),
        ("Ptz.AutoTrack", {"Enable": False}),
        ("fVideo.IntelliTrace", {"Enable": False}),
        ("fVideo.IntelliTrack", {"Enable": False}),
        ("IntelliTrace", {"Enable": False}),
        ("Camera.PtzTrack", {"Enable": False}),
        ("PTZTrack", {"Enable": False, "AutoTrack": False}),

        # Guard Tour
        ("Camera.GuardTour", {"Enable": False}),
        ("Camera.GuardCruise", {"Enable": False}),
        ("GuardTour", {"Enable": False}),
    ]

    for config_name, disable_data in blind_disables:
        if config_name in success:
            continue
        ok, result = xm_set_config(sock, session_id, config_name, disable_data)
        if ok:
            print(f"  ✓ {config_name} → DEAKTIVIERT")
            if config_name not in success:
                success.append(config_name)
        else:
            ret = result.get("Ret", "?") if isinstance(result, dict) else "?"
            # Nur unerwartete Fehler anzeigen (nicht "nicht vorhanden")
            if ret not in (101, 102, 103, 105, 106, 107, 108, 109, 110):
                if config_name not in failed:
                    print(f"  ✗ {config_name} → {_fmt_result(result)}")
                    failed.append(config_name)

    # ---- Strategie 3: OPPTZControl Stop-Befehle ----
    print("\n  --- PTZ-Tracking via OPPTZControl stoppen ---")
    for stop_cmd in ["AutoScanStop", "TourStop", "PatternStop"]:
        stop_data = json.dumps({
            "Name": "OPPTZControl",
            "OPPTZControl": {
                "Command": stop_cmd,
                "Parameter": {
                    "AUX": {"Number": 0, "Status": "On"},
                    "Channel": 0,
                    "MenuOpts": "Enter",
                    "POINT": {"bottom": 0, "left": 0, "right": 0, "top": 0},
                    "Pattern": "SetBegin",
                    "Preset": 0,
                    "Step": 0,
                    "Tour": 0
                }
            },
            "SessionID": f"0x{session_id:08X}"
        }).encode('utf-8') + b'\x0a'
        packet = build_xm_packet(1400, session_id, stop_data)
        sock.sendall(packet)
        msg_id, _, result = parse_xm_response(sock, timeout=2)
        if isinstance(result, dict) and result.get("Ret") in (100, 0):
            print(f"  ✓ {stop_cmd} gesendet")
            success.append(f"PTZ:{stop_cmd}")
        else:
            pass  # Normal wenn kein Tour/Scan aktiv

    return success, failed


def _disable_config(config_data):
    """Setzt alle Enable/Active-Felder in einem Config-Dict auf False/0."""
    if not isinstance(config_data, dict):
        return config_data

    disabled = dict(config_data)
    enable_keys = {"enable", "enabled", "active", "switch",
                   "smdenable", "humanoidenabled", "humanoidenable",
                   "aienable", "autotrack", "autotrackenable",
                   "intellitrace", "intellitrack"}

    for key in list(disabled.keys()):
        if key.lower() in enable_keys:
            if isinstance(disabled[key], bool):
                disabled[key] = False
            elif isinstance(disabled[key], int):
                disabled[key] = 0
            elif isinstance(disabled[key], str) and disabled[key].lower() in ("true", "1", "on"):
                disabled[key] = "false"
        elif isinstance(disabled[key], dict):
            disabled[key] = _disable_config(disabled[key])
        elif isinstance(disabled[key], list):
            disabled[key] = [
                _disable_config(item) if isinstance(item, dict) else item
                for item in disabled[key]
            ]
    return disabled


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
    print("=" * 60)
    print("  Hiseeu HD118-PZ — KI-Tracking Diagnose & Deaktivierung")
    print("  Protokoll: XM Binary (Port 34567)")
    print("=" * 60)
    print()

    # 1. ONVIF-Infos
    cam = get_camera_info()

    # 2. XM Binary Login
    sock, session_id = xm_connect_and_login()
    if sock is None:
        print("\n  ✗ Ohne XM-Verbindung kann das Tracking nicht")
        print("    automatisch deaktiviert werden.")
        print_manual_instructions()
        sys.exit(1)

    try:
        # 3. System-Infos & Fähigkeiten
        scan_system_info(sock, session_id)

        # 4. AI-Konfigurationen auslesen
        found = scan_ai_configs(sock, session_id)

        # 5. Tracking deaktivieren
        success, failed = try_disable_tracking(sock, session_id, found)

        # 6. Ergebnis
        print()
        print("=" * 60)
        if success:
            print(f"ERGEBNIS: {len(success)} Deaktivierung(en) erfolgreich!")
            print("=" * 60)
            for s in success:
                print(f"  ✓ {s}")
            if failed:
                print(f"\n  ({len(failed)} fehlgeschlagen — ist normal,")
                print(f"   verschiedene Firmware-Versionen nutzen verschiedene Namen)")
            print("\n  → Starte 'python3 main.py' und teste ob das Tracking weg ist.")
        else:
            print("ERGEBNIS: Kein automatischer Befehl war erfolgreich")
            print("=" * 60)
            if failed:
                print(f"\n  {len(failed)} Befehle fehlgeschlagen.")
                print("  Die Kamera akzeptiert keine der bekannten Config-Namen.")
            print_manual_instructions()

    finally:
        sock.close()
        print("Verbindung geschlossen.")
