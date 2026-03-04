"""
AI-Tracking Erkennung, Deaktivierung und Watchdog.
"""

import time
import json

from src import xm_protocol as xm
from src import overlay
import src.state as state
from config.config import AI_CHECK_INTERVAL


# ── Config-Namen zum Prüfen ──────────────────────────────────
CHECK_CONFIGS = [
    "Detect.HumanDetection",    # Haupt-Verursacher
    "Camera.PtzAutoTrack",
    "Camera.PTZAutoTrack",
    "fVideo.IntelliTrace",
    "fVideo.IntelliTrack",
]

# ── Config-Namen zum Deaktivieren (breiterer Satz) ───────────
DISABLE_CONFIGS = [
    ("Detect.HumanDetection", {"Enable": False}),
    ("Detect.SmartDetect", {"Enable": False}),
    ("Detect.HumanoidDetect", {"Enable": False}),
    ("Alarm.SmartAlarm", {"Enable": False, "HumanoidEnable": False,
                           "SmdEnable": False, "AiEnable": False}),
    ("Alarm.HumanAlarm", {"Enable": False}),
    ("Alarm.HumanDetection", {"Enable": False}),
    ("fVideo.SmartDetect", {"Enable": False}),
    ("NetWork.NetSmartDetect", {"Enable": False}),
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
    ("Camera.GuardTour", {"Enable": False}),
]


# ── Hilfsfunktion ────────────────────────────────────────────
def _find_enabled(data):
    """Prüft rekursiv ob ein Enable-Feld auf True steht."""
    if isinstance(data, dict):
        for key, val in data.items():
            key_lower = key.lower()
            if key_lower in ("enable", "enabled", "autotrackenable",
                             "humanoidenable", "smdenable", "aienable"):
                if val is True or val == 1 or (
                    isinstance(val, str) and val.lower() in ("true", "1")
                ):
                    return True
            elif isinstance(val, (dict, list)):
                if _find_enabled(val):
                    return True
    elif isinstance(data, list):
        for item in data:
            if _find_enabled(item):
                return True
    return False


# ── Check ────────────────────────────────────────────────────
def check_active(sock=None, session_id=None):
    """
    Prüft ob KI-Tracking auf der Kamera aktiv ist.
    Kann eine bestehende Verbindung wiederverwenden.
    Gibt (aktiv: bool|None, details: list[str]) zurück.
    """
    own_connection = sock is None
    if own_connection:
        sock, session_id = xm.connect_and_login()
        if sock is None:
            return None, ["XM-Verbindung fehlgeschlagen"]

    active_configs = []
    try:
        for config_name in CHECK_CONFIGS:
            ok, data = xm.get_config(sock, session_id, config_name)
            if ok and isinstance(data, dict):
                config_data = data.get(config_name, data)
                if _find_enabled(config_data):
                    active_configs.append(config_name)
    finally:
        if own_connection:
            sock.close()

    return len(active_configs) > 0, active_configs


# ── Disable ──────────────────────────────────────────────────
def disable(sock=None, session_id=None):
    """
    Deaktiviert das KI-Tracking über XM Binary Protocol.
    Gibt die Anzahl erfolgreicher Deaktivierungen zurück.
    """
    own_connection = sock is None
    if own_connection:
        sock, session_id = xm.connect_and_login()
        if sock is None:
            print("  ⚠ XM-Verbindung fehlgeschlagen")
            return 0

    success_count = 0
    try:
        # Config-basierte Deaktivierung
        for config_name, config_data in DISABLE_CONFIGS:
            if xm.set_config(sock, session_id, config_name, config_data):
                success_count += 1

        # PTZ-Stop-Befehle
        for stop_cmd in ["AutoScanStop", "TourStop"]:
            try:
                payload = json.dumps({
                    "Name": "OPPTZControl",
                    "OPPTZControl": {
                        "Command": stop_cmd,
                        "Parameter": {
                            "AUX": {"Number": 0, "Status": "On"}, "Channel": 0,
                            "MenuOpts": "Enter",
                            "POINT": {"bottom": 0, "left": 0, "right": 0, "top": 0},
                            "Pattern": "SetBegin", "Preset": 0, "Step": 0, "Tour": 0
                        }
                    },
                    "SessionID": f"0x{session_id:08X}"
                }).encode('utf-8') + b'\x0a'
                sock.sendall(xm.build_packet(1400, session_id, payload))
                resp = xm.recv_response(sock, timeout=2)
                if isinstance(resp, dict) and resp.get("Ret") in (0, 100):
                    success_count += 1
            except (OSError, ConnectionError):
                break   # Socket tot → Rest überspringen
    finally:
        if own_connection:
            sock.close()

    return success_count


# ── Ensure Disabled ──────────────────────────────────────────
def ensure_disabled():
    """
    Prüft ob AI aktiv ist und deaktiviert sie sofort falls ja.
    Eine einzige TCP-Verbindung für Check + Disable + Verify.
    Gibt (war_aktiv, count, noch_aktiv, details) zurück.
    war_aktiv=None → Verbindungsfehler.
    """
    sock, session_id = xm.connect_and_login()
    if sock is None:
        return None, 0, None, []

    try:
        is_active, details = check_active(sock, session_id)

        if is_active is None:
            return None, 0, None, []
        if not is_active:
            return False, 0, False, []

        count = disable(sock, session_id)
        time.sleep(0.5)
        still_active, still_details = check_active(sock, session_id)
        return True, count, still_active, still_details
    finally:
        sock.close()


# ── Watchdog ─────────────────────────────────────────────────
def watchdog_loop():
    """
    Läuft im Hintergrund und prüft periodisch ob AI-Tracking aktiv ist.
    Bei Erkennung: sofort deaktivieren + visuell warnen.
    """
    time.sleep(5)
    consecutive_failures = 0

    while state.running:
        try:
            sock, session_id = xm.connect_and_login()
            if sock is None:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    print("  ⚠ AI-Watchdog: Kamera nicht erreichbar (3x)")
                    consecutive_failures = 0
            else:
                try:
                    is_active, details = check_active(sock, session_id)

                    if is_active is None:
                        consecutive_failures += 1
                    elif is_active:
                        consecutive_failures = 0
                        state.ai_warning_active = True
                        overlay.ensure_running()
                        print(f"\n  🚨 AI-TRACKING AKTIV ERKANNT: {', '.join(details)}")
                        print("  → Deaktiviere automatisch...")

                        count = disable(sock, session_id)
                        if count > 0:
                            print(f"  ✓ {count} Feature(s) re-deaktiviert")
                            time.sleep(1)
                            still_active, _ = check_active(sock, session_id)
                            if not still_active:
                                print("  ✓ AI-Tracking erfolgreich gestoppt")
                                state.ai_warning_active = False
                            else:
                                print("  ⚠ AI-Tracking IMMER NOCH aktiv!")
                                print("    → Manuell über iCSee/XMEye App deaktivieren!")
                        else:
                            print("  ⚠ Deaktivierung fehlgeschlagen!")
                    else:
                        consecutive_failures = 0
                        if state.ai_warning_active:
                            print("  ✓ AI-Tracking ist jetzt aus.")
                            state.ai_warning_active = False
                finally:
                    sock.close()

        except Exception as e:
            print(f"  AI-Watchdog Fehler: {e}")

        # Warte bis zum nächsten Check (reagiert auf running=False)
        for _ in range(AI_CHECK_INTERVAL * 10):
            if not state.running:
                return
            time.sleep(0.1)
