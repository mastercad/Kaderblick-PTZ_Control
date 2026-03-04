import os
import lgpio
import time
import subprocess
from onvif import ONVIFCamera
import threading

# --- Kamera-Zugangsdaten ---
CAMERA_IP = '192.168.178.122'
CAMERA_PORT = 8899
USERNAME = 'admin'
PASSWORD = ''
RTSP_URL = f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/stream"

# --- GPIO-Pins ---
JOYSTICK_X = 17
JOYSTICK_Y = 27
ZOOM_POT = 22
BUTTON = 23

recording = False
running = True
ffplay_proc = None

# GPIO-Handle für lgpio
gpio_handle = None

# --- Button-Koordinaten (x1, y1, x2, y2) ---
BUTTONS = {
    "start": (20, 400, 170, 470),
    "stop": (200, 400, 350, 470)
}

# --- Setup GPIO ---
def setup_gpio():
    global gpio_handle
    gpio_handle = lgpio.gpiochip_open(0)
    lgpio.gpio_claim_input(gpio_handle, BUTTON, lgpio.SET_PULL_UP)

def cleanup_gpio():
    global gpio_handle
    if gpio_handle is not None:
        lgpio.gpiochip_close(gpio_handle)

def read_button():
    if gpio_handle is not None:
        return lgpio.gpio_read(gpio_handle, BUTTON) == 0
    return False

def read_joystick():
    return 0.0, 0.0

def read_zoom():
    return 0.0

# --- PTZ Steuerung ---
cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
media_service = cam.create_media_service()
ptz_service = cam.create_ptz_service()
profiles = media_service.GetProfiles()
profile = profiles[0]

def move_ptz(x, y, zoom):
    request = ptz_service.create_type('ContinuousMove')
    request.ProfileToken = profile.token
    request.Velocity = {'PanTilt': {'x': x, 'y': y}, 'Zoom': {'x': zoom}}
    ptz_service.ContinuousMove(request)
    time.sleep(0.1)
    ptz_service.Stop({'ProfileToken': profile.token})

# --- Aufnahme ---
ffmpeg_proc = None

def start_recording():
    global ffmpeg_proc, recording
    if ffmpeg_proc is None:
        filename = time.strftime('aufnahme_%Y%m%d_%H%M%S.mp4')
        cmd = [
            'ffmpeg',
            '-i', RTSP_URL,
            '-c:v', 'copy',
            '-an',
            filename
        ]
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

# --- Stream anzeigen über ffplay (Hardware-Decoding) ---
def show_stream():
    global ffplay_proc
    cmd = [
        'ffplay',
        '-fflags', 'nobuffer',
        '-flags', 'low_delay',
        '-x', '1280', '-y', '800',
        '-noborder',
        RTSP_URL
    ]
    ffplay_proc = subprocess.Popen(cmd)
    ffplay_proc.wait()

# --- PTZ + Buttons Loop ---
def control_loop():
    global running
    while running:
        x, y = read_joystick()
        zoom = read_zoom()
        if abs(x) > 0.1 or abs(y) > 0.1 or abs(zoom) > 0.1:
            move_ptz(x, y, zoom)

        if read_button():
            if not recording:
                start_recording()
        else:
            if recording:
                stop_recording()
        time.sleep(0.05)

if __name__ == "__main__":
    setup_gpio()

    # Stream in eigenem Thread anzeigen
    t_stream = threading.Thread(target=show_stream, daemon=True)
    t_stream.start()

    # Steuerungsloop in eigenem Thread
    t_control = threading.Thread(target=control_loop, daemon=True)
    t_control.start()

    try:
        while t_stream.is_alive():
            time.sleep(0.1)
    except KeyboardInterrupt:
        running = False
        cleanup_gpio()
        stop_recording()
        if ffplay_proc is not None:
            ffplay_proc.terminate()
        print("Beendet.")
