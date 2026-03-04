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

current_zoom = 0.5

# --- Utility Funktionen ---
def read_stable_mcp(adc, samples=10):
    return sum(adc.value for _ in range(samples)) / samples

def apply_deadzone(value, center=0.5, deadzone=0.01):
    return center if abs(value - center) < deadzone else value

# --- PTZ Steuerung ---
def move_ptz(x, y, zoom_speed=0, duration=0.05):
    request = ptz_service.create_type('ContinuousMove')
    request.ProfileToken = profile.token
    request.Velocity = {
        'PanTilt': {'x': x, 'y': y},
        'Zoom': {'x': zoom_speed}
    }
    ptz_service.ContinuousMove(request)
    time.sleep(duration)
    ptz_service.Stop({'ProfileToken': profile.token})

def zoom(zoom_value):
    request = ptz_service.create_type('AbsoluteMove')
    request.ProfileToken = profile.token
    request.Position = {'Zoom': {'x': zoom_value}}
    ptz_service.AbsoluteMove(request)

def zoom_to(target_zoom):
    global current_zoom
    step_speed = 0.2  # Geschwindigkeit (0..1)
    if abs(target_zoom - current_zoom) < 0.01:
        return

    zoom_dir = 1 if target_zoom > current_zoom else -1
    request = ptz_service.create_type('ContinuousMove')
    request.ProfileToken = profile.token
    request.Velocity = {'Zoom': {'x': step_speed * zoom_dir}}
    ptz_service.ContinuousMove(request)

    # Zeit proportional zur Differenz
    duration = abs(target_zoom - current_zoom) * 2  # anpassen
    time.sleep(duration)
    ptz_service.Stop({'ProfileToken': profile.token})
    current_zoom = target_zoom

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

# --- Stream Anzeige (direkt, unverändert, skaliert auf Bildschirm) ---
def show_stream():
    global stream_proc
    # Beispiel: Bildschirm 1280x800, unveränderter H264 Stream
    cmd = [
        'mpv',
#        '--profile=fast',
        '-fs',
        RTSP_URL
    ]
    stream_proc = subprocess.Popen(cmd)
    stream_proc.wait()

# --- Steuerungs-Loop ---
def control_loop():
    global running
#    last_zoom_val = read_stable_mcp(pot)
    current_zoom = 0.0
    while running:
        x_val = apply_deadzone(read_stable_mcp(joy_x))
        y_val = apply_deadzone(read_stable_mcp(joy_y))
 #       zoom_val = apply_deadzone(read_stable_mcp(pot))
#        zoom_val = read_stable_mcp(pot)
        target_zoom = read_stable_mcp(pot)
        btn = joy_btn.is_pressed

        # [-1,1] Werte für PTZ
        x_ptz = (x_val - 0.5) * 2
        y_ptz = (y_val - 0.5) * 2
#        zoom_ptz = (zoom_val - 0.5) * 2
#        zoom_speed = (zoom_val - 0.5) * 2 * 0.2

#        zoom_diff = zoom_val - last_zoom_val
#        zoom_speed = max(min(zoom_diff * 3, 1), -1)

        zoom_diff = target_zoom - current_zoom

        if abs(x_ptz) > 0.05 or abs(y_ptz) > 0.05 or abs(zoom_diff) > 0.01:
            zoom_speed = max(min(zoom_diff * 5, 1), -1)
            duration = min(abs(zoom_diff) * 0.2, 0.05)

            move_ptz(x_ptz, y_ptz, zoom_speed, duration)
            current_zoom += zoom_speed * duration
            current_zoom = max(0, min(1, current_zoom))

#        last_zoom_val = zoom_val

#        zoom_to(zoom_val)

#        if last_zoom is None or abs(zoom_val - last_zoom) >  0.01:
#            zoom(zoom_val)
#            last_zoom = zoom_val

        if btn and not recording:
            start_recording()
        elif not btn and recording:
            stop_recording()

        time.sleep(0.05)

# --- Main ---
if __name__ == "__main__":
    try:
        # Stream starten
        t_stream = threading.Thread(target=show_stream, daemon=True)
        t_stream.start()

        # Steuerung starten
        t_control = threading.Thread(target=control_loop, daemon=True)
        t_control.start()

        # Warten, bis Stream beendet
        while t_stream.is_alive():
            time.sleep(0.1)

    except KeyboardInterrupt:
        running = False
        stop_recording()
        if stream_proc is not None:
            stream_proc.terminate()
        print("Beendet.")
