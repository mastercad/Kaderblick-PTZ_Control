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
import subprocess
import threading
import signal
import sys
import requests
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
# KI-Tracking deaktivieren (XM JSON-RPC, POST!)
# ============================================================
def disable_ai_tracking():
    """
    Versucht das KI-Tracking der XM/Xiongmai-Kamera zu deaktivieren.
    Nutzt POST mit JSON-Body (nicht GET — GET gibt nur "Not support GET method").
    """
    print("Versuche KI-Tracking zu deaktivieren...")
    cgi_url = f"http://{CAMERA_IP}/cgi-bin/param.cgi"

    # Befehle mit verschiedenen Parameternamen für verschiedene FW-Versionen
    disable_commands = [
        ("Smart Alarm", "setSmartAlarm", {
            "SmartAlarm": {"Enable": False, "HumanoidEnable": False,
                           "SmdEnable": False, "AiEnable": False}
        }),
        ("Human Detection", "setHumanDetection", {
            "HumanDetection": {"Enable": False}
        }),
        ("Auto-Track", "setAutoTrack", {
            "AutoTrack": {"Enable": False}
        }),
        ("PTZ Auto-Track", "setPTZAutoTrack", {
            "PTZAutoTrack": {"Enable": False}
        }),
        ("Intelli-Trace", "setIntelliTraceConfig", {
            "IntelliTraceConfig": {"Enable": False}
        }),
        ("Guard Tour", "setGuardTour", {
            "GuardTour": {"Enable": False}
        }),
    ]

    success_count = 0
    for name, cmd, params in disable_commands:
        data = {"cmd": cmd}
        data.update(params)
        try:
            r = requests.post(cgi_url, json=data, timeout=3)
            if r.status_code == 200:
                text = r.text.strip()
                # Prüfe ob es WIRKLICH Erfolg war
                if "Not support" in text:
                    continue  # Befehl nicht unterstützt, kein Fehler
                try:
                    result = json.loads(text)
                    ret = result.get("Ret", -1)
                    if ret in (0, 100):
                        print(f"  ✓ {name} deaktiviert")
                        success_count += 1
                except json.JSONDecodeError:
                    pass
        except requests.exceptions.RequestException:
            pass

    if success_count > 0:
        print(f"  {success_count} Feature(s) deaktiviert.")
    else:
        print("  ⚠ Kein Befehl war erfolgreich.")
        print("    → Deaktiviere Tracking manuell über iCSee/XMEye App")
        print("    → oder starte: python3 disable_ai_tracking.py")

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
    # Overlay starten
    overlay_running = True
    overlay_thread = threading.Thread(target=show_overlay, daemon=True)
    overlay_thread.start()

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
# Aufnahme-Overlay (blinkendes "● Aufnahme")
# ============================================================
def show_overlay():
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.attributes('-alpha', 0.7)
    root.configure(bg='black')
    screen_width = root.winfo_screenwidth()
    w, h = 220, 60
    x = screen_width - w - 10
    y = 10
    root.geometry(f'{w}x{h}+{x}+{y}')
    label = tk.Label(
        root, text='● Aufnahme PTZ',
        font=('Arial', 20, 'bold'), fg='red', bg='black'
    )
    label.pack(expand=True, fill='both')
    blink = True

    def update():
        nonlocal blink
        if not overlay_running:
            root.destroy()
            return
        label.config(fg='red' if blink else 'black')
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
    # KI-Tracking beim Start deaktivieren
    disable_ai_tracking()

    print("Starte PTZ-Steuerung...")
    print("  Joystick → Pan/Tilt")
    print("  Poti     → Zoom")
    print("  Button kurz  → Screenshot")
    print("  Button 3s    → Aufnahme Start/Stop")
    print()

    t_stream  = threading.Thread(target=show_stream, daemon=True)
    t_control = threading.Thread(target=control_loop, daemon=True)

    t_stream.start()
    t_control.start()

    # Warten bis Stream-Fenster geschlossen wird
    try:
        while t_stream.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass

    cleanup()
