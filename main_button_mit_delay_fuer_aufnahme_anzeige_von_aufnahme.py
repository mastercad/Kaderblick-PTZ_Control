import time
import subprocess
import threading
from onvif import ONVIFCamera
from gpiozero import MCP3008, Button
# Overlay für Aufnahmeanzeige
import tkinter as tk

# --- Kamera-Zugangsdaten ---
CAMERA_IP = '192.168.178.122'
CAMERA_PORT = 8899
USERNAME = 'admin'
PASSWORD = ''
RTSP_URL = f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/stream"

# --- GPIO / ADC Pins ---
BTN_PIN = 17
pot = MCP3008(channel=0)   # Zoom
joy_y = MCP3008(channel=2)
joy_x = MCP3008(channel=3)
joy_btn = Button(BTN_PIN, pull_up=True)

# --- PTZ Kamera Setup ---
cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
media_service = cam.create_media_service()
ptz_service = cam.create_ptz_service()
profiles = media_service.GetProfiles()
profile = profiles[0]

# --- Aufnahme / Stream ---
recording = False
running = True
stream_proc = None
ffmpeg_proc = None
# Overlay Thread
overlay_thread = None
overlay_running = False

# --- PTZ Einstellungen ---
PAN_MAX = 1.0
TILT_MAX = 1.0
ZOOM_MAX = 1.0
DEADZONE = 0.05
ZOOM_MIN = 1
ZOOM_MAX_STEPS = 30
LOOP_SLEEP = 0.04

def start_recording():
    global ffmpeg_proc, recording, overlay_thread, overlay_running
    if ffmpeg_proc is None:
        filename = time.strftime('aufnahme_%Y%m%d_%H%M%S.mp4')
        cmd = ['ffmpeg', '-i', RTSP_URL, '-c:v', 'copy', '-an', filename]
        ffmpeg_proc = subprocess.Popen(cmd)
        recording = True
        print(f"Aufnahme gestartet: {filename}")
        # Overlay starten
        overlay_running = True
        overlay_thread = threading.Thread(target=show_overlay, daemon=True)
        overlay_thread.start()

def stop_recording():
    global ffmpeg_proc, recording, overlay_running
    if ffmpeg_proc is not None:
        ffmpeg_proc.terminate()
        ffmpeg_proc.wait()
        ffmpeg_proc = None
        recording = False
        print("Aufnahme gestoppt.")
        # Overlay stoppen
        overlay_running = False

# --- Screenshot Funktion ---
def take_screenshot():
    filename = time.strftime('screenshot_%Y%m%d_%H%M%S.jpg')
    cmd = ['ffmpeg', '-y', '-i', RTSP_URL, '-frames:v', '1', filename]
    subprocess.run(cmd)
    print(f"Screenshot aufgenommen: {filename}")

def show_stream():
    global stream_proc
    cmd = ['mpv', '-fs', RTSP_URL]
    stream_proc = subprocess.Popen(cmd)
    stream_proc.wait()

# --- Overlay Anzeige ---
def show_overlay():
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.attributes('-alpha', 0.7)
    root.configure(bg='black')
    # Bildschirmgröße ermitteln
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    # Fenstergröße und Position oben rechts
    w, h = 220, 60
    x = screen_width - w - 10
    y = 10
    root.geometry(f'{w}x{h}+{x}+{y}')
    label = tk.Label(root, text='● Aufnahme PTZ', font=('Arial', 20, 'bold'), fg='red', bg='black')
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

# --- PTZ Steuerung ---
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
        print("ContinuousMove Fehler:", e)

def send_stop():
    try:
        ptz_service.Stop({'ProfileToken': profile.token})
    except Exception as e:
        print("Stop Fehler:", e)

# --- Steuerungs-Loop ---
def control_loop():
    global running, recording

    btn_last_state = False
    btn_press_time = None
    btn_action_done = False

    while running:
        # Werte vom Joystick (0..1023)
        raw_x = int(joy_x.value * 1023)
        raw_y = int(joy_y.value * 1023)
        raw_z = int(pot.value * 1023)

        pan = (raw_x / 1023 * 2 - 1) * PAN_MAX
        tilt = (raw_y / 1023 * 2 - 1) * TILT_MAX

        if abs(pan) < DEADZONE:
            pan = 0.0
        if abs(tilt) < DEADZONE:
            tilt = 0.0

        zoom_speed = 0.0
        if raw_z < 400:
            zoom_speed = - (400 - raw_z) / 400 * ZOOM_MAX
        elif raw_z > 600:
            zoom_speed = (raw_z - 600) / (1023 - 600) * ZOOM_MAX
        else:
            zoom_speed = 0.0

        if pan != 0.0 or tilt != 0.0 or zoom_speed != 0.0:
            send_continuous_move(pan, tilt, zoom_speed)
        else:
            send_stop()

        # Button-Logik
        btn_state = joy_btn.is_pressed
        now = time.time()

        if btn_state and not btn_last_state:
            # Button wurde gerade gedrückt
            btn_press_time = now
            btn_action_done = False
        elif btn_state and btn_press_time is not None:
            # Button wird gehalten
            if not btn_action_done and now - btn_press_time > 3.0:
                if not recording:
                    start_recording()
                else:
                    stop_recording()
                btn_action_done = True
        elif not btn_state and btn_last_state:
            # Button wurde losgelassen
            if btn_press_time is not None and not btn_action_done:
                duration = now - btn_press_time
                if duration < 3.0:
                    take_screenshot()
            btn_press_time = None
            btn_action_done = False

        btn_last_state = btn_state
        time.sleep(0.04)

# --- Main ---
if __name__ == "__main__":
    try:
        t_stream = threading.Thread(target=show_stream, daemon=True)
        t_stream.start()

        t_control = threading.Thread(target=control_loop, daemon=True)
        t_control.start()

        while t_stream.is_alive():
            time.sleep(0.1)

    except KeyboardInterrupt:
        running = False
        stop_recording()
        if stream_proc is not None:
            stream_proc.terminate()
        print("Beendet.")
