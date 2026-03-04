"""
PTZ-Steuerung für Hiseeu HD118-PZ — Fußball-Aufnahme
=====================================================
Optimiert für minimale Latenz bei der Live-Vorschau und maximale
Qualität bei der Aufnahme.

Steuerung:
  - Joystick X/Y    → Pan/Tilt
  - Poti (CH0)      → Zoom
  - Button kurz     → Screenshot
  - Button lang 3s  → Aufnahme Start/Stop

Latenz-Optimierungen:
  - Live-Vorschau über Sub-Stream (niedrigere Auflösung, weniger Daten)
  - mpv mit aggressiven Low-Latency-Einstellungen
  - PTZ-Befehle nur bei Änderung (kein Spam bei Stillstand)
  - Aufnahme immer über Main-Stream in voller 4K-Qualität
"""

import time
import os
import json
import socket
import struct
import hashlib
import subprocess
import threading
import signal
import sys
from onvif import ONVIFCamera
from gpiozero import MCP3008, Button
import tkinter as tk

# ============================================================
# Konfiguration
# ============================================================
CAMERA_IP = '192.168.178.122'
CAMERA_PORT = 8899           # ONVIF-Port
USERNAME = 'admin'
PASSWORD = ''

# RTSP-Streams — Main-Stream für Aufnahme, Sub-Stream für Live-Vorschau
# Der Sub-Stream hat niedrigere Auflösung → weniger Daten → weniger Latenz
RTSP_MAIN = f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/stream"
RTSP_SUB  = f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/stream2"

# Aufnahme-Ordner
RECORDING_DIR = os.path.expanduser("~/Aufnahmen")
os.makedirs(RECORDING_DIR, exist_ok=True)

# GPIO / ADC Pins (MCP3008 über SPI)
BTN_PIN = 17
pot   = MCP3008(channel=0)   # Zoom-Poti
joy_y = MCP3008(channel=2)   # Joystick Y-Achse
joy_x = MCP3008(channel=3)   # Joystick X-Achse
joy_btn = Button(BTN_PIN, pull_up=True)

# PTZ-Einstellungen
PAN_MAX  = 1.0
TILT_MAX = 1.0
ZOOM_MAX = 1.0
DEADZONE = 0.08    # etwas größere Deadzone → weniger Jitter
ZOOM_DEADZONE_LO = 400   # Poti-Mittelbereich (kein Zoom)
ZOOM_DEADZONE_HI = 600
LOOP_SLEEP = 0.05  # 20 Hz Steuer-Loop reicht für flüssige Kontrolle

# ============================================================
# Globale Variablen
# ============================================================
recording = False
running = True
stream_proc = None
ffmpeg_proc = None
overlay_thread = None
overlay_running = False
ai_warning_active = False      # True wenn AI-Tracking erkannt wurde
ai_watchdog_thread = None

# ============================================================
# ONVIF Kamera-Setup
# ============================================================
print("Verbinde mit Kamera über ONVIF...")
cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
media_service = cam.create_media_service()
ptz_service   = cam.create_ptz_service()
profiles = media_service.GetProfiles()
profile  = profiles[0]
print(f"Verbunden. Profil: {profile.Name}")

# ============================================================
# XM Binary Protocol — Verbindung & Hilfsfunktionen
# ============================================================
def _xm_hash_password(password):
    """XM-Kameras nutzen ein spezielles Password-Hashing."""
    m = hashlib.md5(password.encode('utf-8') if password else b"").digest()
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    return "".join(chars[(m[2*i] + m[2*i+1]) % len(chars)] for i in range(8))


def _xm_build_packet(msg_id, session_id, data_bytes):
    """Baut ein XM/DVRIP-Paket (20 Byte Header + Daten)."""
    header = struct.pack(
        '<BBBB I I BB H I',
        0xFF, 0x00, 0x00, 0x00,
        session_id, 0, 0, 0,
        msg_id, len(data_bytes),
    )
    return header + data_bytes


def _xm_recv_response(sock, timeout=3):
    """Empfängt und parst eine XM/DVRIP-Antwort."""
    sock.settimeout(timeout)
    try:
        header = b''
        while len(header) < 20:
            chunk = sock.recv(20 - len(header))
            if not chunk:
                return None
            header += chunk
        _, _, _, _, _, _, _, _, msg_id, data_len = struct.unpack('<BBBB I I BB H I', header)
        data = b''
        while len(data) < data_len:
            chunk = sock.recv(min(data_len - len(data), 4096))
            if not chunk:
                break
            data += chunk
        return json.loads(data.rstrip(b'\x00\x0a').decode('utf-8', errors='replace'))
    except Exception:
        return None


def _xm_connect_and_login():
    """
    Stellt eine XM-Verbindung her und loggt ein.
    Gibt (sock, session_id) zurück oder (None, None) bei Fehler.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((CAMERA_IP, 34567))
    except Exception:
        return None, None

    hashed_pw = _xm_hash_password(PASSWORD)
    login_data = json.dumps({
        "EncryptType": "MD5", "LoginType": "DVRIP-Web",
        "PassWord": hashed_pw, "UserName": USERNAME
    }).encode('utf-8') + b'\x0a'
    sock.sendall(_xm_build_packet(1000, 0, login_data))
    result = _xm_recv_response(sock)

    if not isinstance(result, dict) or result.get("Ret") != 100:
        sock.close()
        return None, None

    session_str = result.get("SessionID", "0x00000000")
    session_id = int(session_str, 16) if isinstance(session_str, str) and session_str.startswith("0x") else 0
    return sock, session_id


def _xm_get_config(sock, session_id, config_name):
    """Liest eine Konfiguration. Gibt (erfolg, daten) zurück."""
    payload = json.dumps({
        "Name": config_name,
        "SessionID": f"0x{session_id:08X}"
    }).encode('utf-8') + b'\x0a'
    sock.sendall(_xm_build_packet(1042, session_id, payload))
    resp = _xm_recv_response(sock, timeout=2)
    if isinstance(resp, dict) and resp.get("Ret") in (0, 100):
        return True, resp
    return False, resp


def _xm_set_config(sock, session_id, config_name, config_data):
    """Setzt eine Konfiguration. Gibt True/False zurück."""
    payload = json.dumps({
        "Name": config_name,
        config_name: config_data,
        "SessionID": f"0x{session_id:08X}"
    }).encode('utf-8') + b'\x0a'
    sock.sendall(_xm_build_packet(1040, session_id, payload))
    resp = _xm_recv_response(sock, timeout=2)
    return isinstance(resp, dict) and resp.get("Ret") in (0, 100)


# ============================================================
# AI-Tracking Check — prüft ob HumanDetection etc. aktiv ist
# ============================================================
# Config-Namen die auf AI-Tracking hindeuten
AI_CHECK_CONFIGS = [
    "Detect.HumanDetection",    # Haupt-Verursacher (war bei dir aktiv!)
    "Camera.PtzAutoTrack",
    "Camera.PTZAutoTrack",
    "fVideo.IntelliTrace",
    "fVideo.IntelliTrack",
]

# Alle Config-Namen zum Deaktivieren (breiterer Satz)
AI_DISABLE_CONFIGS = [
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


def _find_enabled_in_config(data):
    """
    Prüft rekursiv ob ein Enable-Feld auf True steht.
    Gibt True zurück wenn irgendeine AI-relevante Einstellung aktiv ist.
    """
    if isinstance(data, dict):
        for key, val in data.items():
            key_lower = key.lower()
            if key_lower in ("enable", "enabled", "autotrackenable",
                             "humanoidenable", "smdenable", "aienable"):
                if val is True or val == 1 or (isinstance(val, str) and val.lower() in ("true", "1")):
                    return True
            elif isinstance(val, (dict, list)):
                if _find_enabled_in_config(val):
                    return True
    elif isinstance(data, list):
        for item in data:
            if _find_enabled_in_config(item):
                return True
    return False


def check_ai_tracking_active():
    """
    Prüft ob KI-Tracking auf der Kamera aktiv ist.
    Gibt (aktiv: bool, details: list[str]) zurück.
    """
    sock, session_id = _xm_connect_and_login()
    if sock is None:
        return None, ["XM-Verbindung fehlgeschlagen"]

    active_configs = []
    try:
        for config_name in AI_CHECK_CONFIGS:
            ok, data = _xm_get_config(sock, session_id, config_name)
            if ok and isinstance(data, dict):
                config_data = data.get(config_name, data)
                if _find_enabled_in_config(config_data):
                    active_configs.append(config_name)
    finally:
        sock.close()

    is_active = len(active_configs) > 0
    return is_active, active_configs


def disable_ai_tracking():
    """
    Deaktiviert das KI-Tracking über XM Binary Protocol (Port 34567).
    Gibt die Anzahl erfolgreicher Deaktivierungen zurück.
    """
    sock, session_id = _xm_connect_and_login()
    if sock is None:
        print("  ⚠ XM-Verbindung fehlgeschlagen")
        return 0

    success_count = 0
    try:
        # Config-basierte Deaktivierung
        for config_name, config_data in AI_DISABLE_CONFIGS:
            if _xm_set_config(sock, session_id, config_name, config_data):
                success_count += 1

        # PTZ-Stop-Befehle
        for stop_cmd in ["AutoScanStop", "TourStop"]:
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
            sock.sendall(_xm_build_packet(1400, session_id, payload))
            resp = _xm_recv_response(sock, timeout=2)
            if isinstance(resp, dict) and resp.get("Ret") in (0, 100):
                success_count += 1
    finally:
        sock.close()

    return success_count


def ensure_ai_disabled():
    """
    Prüft ob AI aktiv ist und deaktiviert sie sofort falls ja.
    Gibt (war_aktiv, anzahl_deaktiviert) zurück.
    """
    is_active, details = check_ai_tracking_active()

    if is_active is None:
        # Verbindung fehlgeschlagen
        return None, 0

    if not is_active:
        return False, 0

    # AI ist aktiv! Sofort deaktivieren
    count = disable_ai_tracking()
    return True, count


# ============================================================
# AI-Watchdog — periodische Überwachung im Hintergrund
# ============================================================
AI_CHECK_INTERVAL = 30  # Sekunden zwischen den Checks

def ai_watchdog_loop():
    """
    Läuft im Hintergrund und prüft periodisch ob AI-Tracking aktiv ist.
    Bei Erkennung: sofort deaktivieren + visuell warnen.
    """
    global ai_warning_active

    # Erster Check direkt nach Start
    time.sleep(5)

    consecutive_failures = 0

    while running:
        try:
            is_active, details = check_ai_tracking_active()

            if is_active is None:
                # Verbindungsfehler — nicht sofort panik machen
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    print("  ⚠ AI-Watchdog: Kamera nicht erreichbar (3x)")
                    consecutive_failures = 0
            elif is_active:
                consecutive_failures = 0
                ai_warning_active = True
                _ensure_overlay_running()
                detail_str = ", ".join(details)
                print(f"\n  🚨 AI-TRACKING AKTIV ERKANNT: {detail_str}")
                print(f"  → Deaktiviere automatisch...")

                count = disable_ai_tracking()
                if count > 0:
                    print(f"  ✓ {count} Feature(s) re-deaktiviert")
                    # Nochmal prüfen ob es gewirkt hat
                    time.sleep(1)
                    still_active, _ = check_ai_tracking_active()
                    if not still_active:
                        print(f"  ✓ AI-Tracking erfolgreich gestoppt")
                        ai_warning_active = False
                    else:
                        print(f"  ⚠ AI-Tracking IMMER NOCH aktiv!")
                        print(f"    → Manuell über iCSee/XMEye App deaktivieren!")
                else:
                    print(f"  ⚠ Deaktivierung fehlgeschlagen!")
            else:
                consecutive_failures = 0
                if ai_warning_active:
                    print(f"  ✓ AI-Tracking ist jetzt aus.")
                    ai_warning_active = False

        except Exception as e:
            print(f"  AI-Watchdog Fehler: {e}")

        # Warte bis zum nächsten Check (aber reagiere auf running=False)
        for _ in range(AI_CHECK_INTERVAL * 10):
            if not running:
                return
            time.sleep(0.1)

def _ensure_overlay_running():
    """Startet das Overlay falls es nicht schon läuft."""
    global overlay_thread, overlay_running
    if overlay_thread is not None and overlay_thread.is_alive():
        return  # Läuft schon
    overlay_running = True
    overlay_thread = threading.Thread(target=show_overlay, daemon=True)
    overlay_thread.start()


# ============================================================
# Aufnahme (Main-Stream in voller Qualität)
# ============================================================
def start_recording():
    global ffmpeg_proc, recording, overlay_thread, overlay_running
    if ffmpeg_proc is not None:
        return
    filename = time.strftime('aufnahme_%Y%m%d_%H%M%S.mp4')
    filepath = os.path.join(RECORDING_DIR, filename)
    cmd = [
        'ffmpeg',
        '-rtsp_transport', 'tcp',     # TCP ist stabiler als UDP
        '-i', RTSP_MAIN,              # Main-Stream für volle Qualität
        '-c:v', 'copy',               # Kein Re-Encoding → keine CPU-Last
        '-c:a', 'aac',                # Audio konvertieren (pcm_alaw → aac)
        '-movflags', '+faststart',    # Schnelleres Abspielen nach Aufnahme
        '-y', filepath
    ]
    ffmpeg_proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    recording = True
    print(f"🔴 Aufnahme gestartet: {filepath}")
    _ensure_overlay_running()

def stop_recording():
    global ffmpeg_proc, recording, overlay_running
    if ffmpeg_proc is None:
        return
    # Sauberes Beenden mit SIGINT → ffmpeg schreibt Container-Ende
    ffmpeg_proc.send_signal(signal.SIGINT)
    try:
        ffmpeg_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        ffmpeg_proc.terminate()
        ffmpeg_proc.wait()
    ffmpeg_proc = None
    recording = False
    overlay_running = False
    print("⬛ Aufnahme gestoppt.")

# ============================================================
# Screenshot
# ============================================================
def take_screenshot():
    filename = time.strftime('screenshot_%Y%m%d_%H%M%S.jpg')
    filepath = os.path.join(RECORDING_DIR, filename)
    cmd = [
        'ffmpeg', '-y',
        '-rtsp_transport', 'tcp',
        '-i', RTSP_MAIN,
        '-frames:v', '1',
        '-q:v', '2',
        filepath
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"📸 Screenshot: {filepath}")

# ============================================================
# Live-Vorschau (Sub-Stream, Low-Latency)
# ============================================================
def show_stream():
    """
    Zeigt den Sub-Stream mit aggressiven Low-Latency-Einstellungen.
    Falls der Sub-Stream nicht verfügbar ist, fällt es auf den
    Main-Stream zurück (mit Latenz-Optimierungen).
    """
    global stream_proc

    # mpv Low-Latency Konfiguration
    cmd = [
        'mpv',
        '--fullscreen',
        '--no-audio',                       # Audio weglassen → weniger Puffer
        '--profile=low-latency',            # mpv eingebautes Low-Latency-Profil
        '--untimed',                        # Frames sofort anzeigen
        '--no-cache',                       # Kein Cache
        '--cache-pause=no',                 # Nie pausieren um zu puffern
        '--demuxer-lavf-o=fflags=+nobuffer+fastseek', # ffmpeg: kein Puffer
        '--demuxer-lavf-o=rtsp_transport=tcp',        # TCP statt UDP
        '--demuxer-readahead-secs=0',       # Kein Vorauslesen
        '--interpolation=no',               # Kein Frame-Interpolation
        '--video-sync=audio',               # Kein Audio → Display-Sync
        '--video-latency-hacks=yes',        # Experimentelle Latenz-Hacks
        '--vd-lavc-threads=4',              # Mehr Decoder-Threads
        '--hwdec=auto-safe',                # Hardware-Decoding wenn möglich
        '--force-seekable=no',              # Kein Seeking → Live
        f'--title=PTZ Live',
        RTSP_SUB                            # Sub-Stream verwenden!
    ]

    print(f"Starte Live-Vorschau (Sub-Stream)...")
    stream_proc = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
    retcode = stream_proc.wait()

    # Fallback auf Main-Stream wenn Sub-Stream nicht verfügbar
    if retcode != 0:
        print("Sub-Stream nicht verfügbar, versuche Main-Stream...")
        cmd[-1] = RTSP_MAIN
        stream_proc = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
        stream_proc.wait()

# ============================================================
# Aufnahme-Overlay (blinkendes "● Aufnahme" + AI-Warnung)
# ============================================================
def show_overlay():
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.attributes('-alpha', 0.7)
    root.configure(bg='black')
    screen_width = root.winfo_screenwidth()
    w, h = 280, 100
    x = screen_width - w - 10
    y = 10
    root.geometry(f'{w}x{h}+{x}+{y}')

    # Aufnahme-Label
    rec_label = tk.Label(
        root, text='● Aufnahme PTZ',
        font=('Arial', 18, 'bold'), fg='red', bg='black'
    )
    rec_label.pack(fill='x', pady=(5, 0))

    # AI-Warnung-Label (nur sichtbar wenn AI aktiv)
    ai_label = tk.Label(
        root, text='',
        font=('Arial', 14, 'bold'), fg='yellow', bg='black'
    )
    ai_label.pack(fill='x', pady=(2, 5))

    blink = True

    def update():
        nonlocal blink
        if not overlay_running and not ai_warning_active:
            root.destroy()
            return

        # Aufnahme-Indikator
        if overlay_running:
            rec_label.config(
                text='● Aufnahme PTZ',
                fg='red' if blink else 'darkred'
            )
        else:
            rec_label.config(text='', fg='black')

        # AI-Warnung
        if ai_warning_active:
            ai_label.config(
                text='⚠ AI-TRACKING AKTIV!' if blink else '  AI-TRACKING AKTIV!',
                fg='yellow' if blink else 'red'
            )
        else:
            ai_label.config(text='', fg='black')

        # Fenster-Größe anpassen
        if overlay_running and ai_warning_active:
            root.geometry(f'{w}x{h}+{x}+{y}')
        elif overlay_running or ai_warning_active:
            root.geometry(f'{w}x60+{x}+{y}')

        blink = not blink
        root.after(500, update)

    update()
    root.mainloop()

# ============================================================
# PTZ-Steuerung — nur bei Änderung senden!
# ============================================================
def send_continuous_move(pan, tilt, zoom_speed):
    try:
        req = ptz_service.create_type('ContinuousMove')
        req.ProfileToken = profile.token
        req.Velocity = {
            'PanTilt': {'x': float(pan), 'y': float(tilt)},
            'Zoom': {'x': float(zoom_speed)}
        }
        ptz_service.ContinuousMove(req)
    except Exception as e:
        print(f"PTZ ContinuousMove Fehler: {e}")

def send_stop():
    try:
        ptz_service.Stop({'ProfileToken': profile.token})
    except Exception as e:
        print(f"PTZ Stop Fehler: {e}")

# ============================================================
# Steuerungs-Loop
# ============================================================
def control_loop():
    global running, recording

    btn_last_state = False
    btn_press_time = None
    btn_action_done = False

    # Zustand merken → nur bei Veränderung Befehle senden
    prev_moving = False
    prev_pan = 0.0
    prev_tilt = 0.0
    prev_zoom = 0.0
    change_threshold = 0.03   # Minimale Änderung bevor neuer Befehl gesendet wird

    while running:
        # Joystick/Poti auslesen (0.0 .. 1.0 → normalisiert auf -1.0 .. 1.0)
        raw_x = joy_x.value
        raw_y = joy_y.value
        raw_z = int(pot.value * 1023)

        pan  = (raw_x * 2.0 - 1.0) * PAN_MAX
        tilt = (raw_y * 2.0 - 1.0) * TILT_MAX

        # Deadzone anwenden
        if abs(pan) < DEADZONE:
            pan = 0.0
        if abs(tilt) < DEADZONE:
            tilt = 0.0

        # Zoom aus Poti (Mittelstellung = kein Zoom)
        zoom_speed = 0.0
        if raw_z < ZOOM_DEADZONE_LO:
            zoom_speed = -(ZOOM_DEADZONE_LO - raw_z) / ZOOM_DEADZONE_LO * ZOOM_MAX
        elif raw_z > ZOOM_DEADZONE_HI:
            zoom_speed = (raw_z - ZOOM_DEADZONE_HI) / (1023 - ZOOM_DEADZONE_HI) * ZOOM_MAX

        # Ist Bewegung aktiv?
        is_moving = (pan != 0.0 or tilt != 0.0 or zoom_speed != 0.0)

        # Nur senden wenn sich etwas geändert hat
        if is_moving:
            value_changed = (
                abs(pan - prev_pan) > change_threshold or
                abs(tilt - prev_tilt) > change_threshold or
                abs(zoom_speed - prev_zoom) > change_threshold
            )
            if not prev_moving or value_changed:
                send_continuous_move(pan, tilt, zoom_speed)
                prev_pan = pan
                prev_tilt = tilt
                prev_zoom = zoom_speed
        elif prev_moving:
            # War in Bewegung, jetzt Stillstand → einmal Stop senden
            send_stop()

        prev_moving = is_moving

        # ---- Button-Logik (kurz = Screenshot, lang = Aufnahme) ----
        btn_state = joy_btn.is_pressed
        now = time.time()

        if btn_state and not btn_last_state:
            btn_press_time = now
            btn_action_done = False
        elif btn_state and btn_press_time is not None:
            if not btn_action_done and now - btn_press_time > 3.0:
                if not recording:
                    start_recording()
                else:
                    stop_recording()
                btn_action_done = True
        elif not btn_state and btn_last_state:
            if btn_press_time is not None and not btn_action_done:
                if now - btn_press_time < 3.0:
                    take_screenshot()
            btn_press_time = None
            btn_action_done = False

        btn_last_state = btn_state
        time.sleep(LOOP_SLEEP)

# ============================================================
# Sauberes Beenden
# ============================================================
def cleanup(signum=None, frame=None):
    global running
    running = False
    print("\nBeende...")
    stop_recording()
    if stream_proc is not None:
        stream_proc.terminate()
    send_stop()
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    # Beim Start: AI prüfen und deaktivieren
    print("Prüfe AI-Tracking Status...")
    was_active, count = ensure_ai_disabled()
    if was_active is None:
        print("  ⚠ Konnte AI-Status nicht prüfen (Verbindungsfehler)")
        print("    → Versuche trotzdem blind zu deaktivieren...")
        count = disable_ai_tracking()
        if count > 0:
            print(f"  ✓ {count} Feature(s) deaktiviert")
        else:
            print("  ⚠ Deaktivierung fehlgeschlagen")
            print("    → Ggf. manuell über iCSee/XMEye App deaktivieren")
    elif was_active:
        print(f"  🚨 AI-Tracking war AKTIV → {count} Feature(s) deaktiviert")
        # Verifizieren
        still_active, details = check_ai_tracking_active()
        if still_active:
            print(f"  ⚠ WARNUNG: AI immer noch aktiv: {', '.join(details)}")
            ai_warning_active = True
        else:
            print(f"  ✓ AI-Tracking erfolgreich deaktiviert")
    else:
        print(f"  ✓ AI-Tracking ist AUS — alles gut!")

    print()
    print("Starte PTZ-Steuerung...")
    print("  Joystick → Pan/Tilt")
    print("  Poti     → Zoom")
    print("  Button kurz  → Screenshot")
    print("  Button 3s    → Aufnahme Start/Stop")
    print(f"  AI-Watchdog   → prüft alle {AI_CHECK_INTERVAL}s (automatische Re-Deaktivierung)")
    print()

    t_stream   = threading.Thread(target=show_stream, daemon=True)
    t_control  = threading.Thread(target=control_loop, daemon=True)
    t_watchdog = threading.Thread(target=ai_watchdog_loop, daemon=True)

    t_stream.start()
    t_control.start()
    t_watchdog.start()

    # Overlay wenn AI-Warnung beim Start schon aktiv
    if ai_warning_active:
        _ensure_overlay_running()

    # Warten bis Stream-Fenster geschlossen wird
    try:
        while t_stream.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass

    cleanup()
