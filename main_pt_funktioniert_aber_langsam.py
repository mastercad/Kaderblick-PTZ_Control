import time
import subprocess
import threading
from onvif import ONVIFCamera
from gpiozero import MCP3008, Button

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

# --- PTZ Einstellungen ---
PAN_MAX = 1.0
TILT_MAX = 1.0
ZOOM_MAX = 1.0
DEADZONE = 0.05
ZOOM_STEPS = 30

# --- Aufnahme Funktionen ---
def start_recording():
    global ffmpeg_proc, recording
    if ffmpeg_proc is None:
        filename = time.strftime('aufnahme_%Y%m%d_%H%M%S.mp4')
        cmd = ['ffmpeg', '-i', RTSP_URL, '-c:v', 'copy', '-an', filename]
        ffmpeg_proc = subprocess.Popen(cmd)
        recording = True
        print(f"Aufnahme gestartet: {filename}")

def stop_recording():
    global ffmpeg_proc, recording
    if ffmpeg_proc is not None:
        ffmpeg_proc.terminate()
        ffmpeg_proc.wait()
        ffmpeg_proc = None
        recording = False
        print("Aufnahme gestoppt.")

# --- Stream Anzeige ---
def show_stream():
    global stream_proc
    cmd = ['mpv', '-fs', RTSP_URL]
    stream_proc = subprocess.Popen(cmd)
    stream_proc.wait()

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
    current_zoom_step = -1

    while running:
        # Werte vom Joystick (0..1)
        raw_x = joy_x.value
        raw_y = joy_y.value
        raw_z = pot.value

        # Proportional -1..1
        pan = (raw_x * 2 - 1) * PAN_MAX
        tilt = (raw_y * 2 - 1) * TILT_MAX

        # Deadzone
        if abs(pan) < DEADZONE:
            pan = 0.0
        if abs(tilt) < DEADZONE:
            tilt = 0.0

        # Zoom in 30 Stufen
        zoom_step = int(raw_z * (ZOOM_STEPS - 1))
        zoom_speed = 0.0

        if zoom_step > current_zoom_step:
            zoom_speed = ZOOM_MAX
        elif zoom_step < current_zoom_step:
            zoom_speed = -ZOOM_MAX

        # Wenn Zoom sich ändern muss, sende ContinuousMove kurz und Stop
        if zoom_step != current_zoom_step:
            if zoom_speed != 0:
                send_continuous_move(0.0, 0.0, zoom_speed)
                # Dauer proportional zur Stufendifferenz
                time.sleep(abs(zoom_step - current_zoom_step) * 0.05)
                send_stop()
            current_zoom_step = zoom_step

        # Pan/Tilt nur senden wenn Bewegung
        if pan != 0.0 or tilt != 0.0:
            send_continuous_move(pan, tilt, 0.0)
        else:
            send_stop()

        # Aufnahme
        if joy_btn.is_pressed and not recording:
            start_recording()
        elif not joy_btn.is_pressed and recording:
            stop_recording()

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
