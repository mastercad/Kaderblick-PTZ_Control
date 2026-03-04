import os
import lgpio
import time
import subprocess
from onvif import ONVIFCamera
import threading
from gpiozero import MCP3008, Button

# --- Kamera-Zugangsdaten ---
CAMERA_IP = '192.168.178.122'
CAMERA_PORT = 8899
USERNAME = 'admin'
PASSWORD = ''
RTSP_URL = f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/stream"

# --- GPIO / ADC Pins ---
BTN_PIN = 17  # Joystick Button
pot = MCP3008(channel=0)   # Zoom
joy_y = MCP3008(channel=2) # Joystick Y
joy_x = MCP3008(channel=3) # Joystick X
joy_btn = Button(BTN_PIN, pull_up=True)

# --- Aufnahme / Stream ---
recording = False
running = True
ffplay_proc = None
ffmpeg_proc = None

# --- PTZ Kamera Setup ---
cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
media_service = cam.create_media_service()
ptz_service = cam.create_ptz_service()
profiles = media_service.GetProfiles()
profile = profiles[0]

# --- Utility Funktionen für MCP3008 ---
def read_stable_mcp(adc, samples=10):
    """Mittelwert aus mehreren Samples vom MCP3008."""
    total = 0.0
    for _ in range(samples):
        total += adc.value
    return total / samples

def apply_deadzone(value, center=0.5, deadzone=0.01):
    if abs(value - center) < deadzone:
        return center
    return value

# --- PTZ Steuerung ---
def move_ptz(x, y, zoom):
    request = ptz_service.create_type('ContinuousMove')
    request.ProfileToken = profile.token
    request.Velocity = {'PanTilt': {'x': x, 'y': y}, 'Zoom': {'x': zoom}}
    ptz_service.ContinuousMove(request)
    time.sleep(0.1)
    ptz_service.Stop({'ProfileToken': profile.token})

# --- Aufnahme Funktionen ---
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

# --- Stream anzeigen (hardwarebeschleunigt) ---
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

# --- Steuerungs-Loop für Joystick und Potentiometer ---
def control_loop():
    global running
    while running:
        # MCP3008 Werte auslesen
        x_val = apply_deadzone(read_stable_mcp(joy_x))
        y_val = apply_deadzone(read_stable_mcp(joy_y))
        zoom_val = apply_deadzone(read_stable_mcp(pot))
        btn = joy_btn.is_pressed

        # Werte für PTZ [-1,1] berechnen
        x_ptz = (x_val - 0.5) * 2  # Joystick X
        y_ptz = (y_val - 0.5) * 2  # Joystick Y
        zoom_ptz = (zoom_val - 0.5) * 2

        # PTZ bewegen, falls Werte außerhalb Deadzone
        if abs(x_ptz) > 0.05 or abs(y_ptz) > 0.05 or abs(zoom_ptz) > 0.05:
            move_ptz(x_ptz, y_ptz, zoom_ptz)

        # Aufnahme starten/stoppen
        if btn:
            if not recording:
                start_recording()
        else:
            if recording:
                stop_recording()

        time.sleep(0.05)

if __name__ == "__main__":
    try:
        # Stream starten
        t_stream = threading.Thread(target=show_stream, daemon=True)
        t_stream.start()

        # Steuerungsloop starten
        t_control = threading.Thread(target=control_loop, daemon=True)
        t_control.start()

        # Hauptthread wartet, bis Stream beendet
        while t_stream.is_alive():
            time.sleep(0.1)

    except KeyboardInterrupt:
        running = False
        stop_recording()
        if ffplay_proc is not None:
            ffplay_proc.terminate()
        print("Beendet.")
