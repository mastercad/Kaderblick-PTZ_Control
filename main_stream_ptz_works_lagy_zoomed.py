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
ffmpeg_proc = None
gst_proc = None

# --- Utility Funktionen ---
def read_stable_mcp(adc, samples=10):
    total = sum(adc.value for _ in range(samples))
    return total / samples

def apply_deadzone(value, center=0.5, deadzone=0.01):
    return center if abs(value - center) < deadzone else value

# --- PTZ Steuerung ---
def move_ptz(x, y, zoom):
    request = ptz_service.create_type('ContinuousMove')
    request.ProfileToken = profile.token
    request.Velocity = {'PanTilt': {'x': x, 'y': y}, 'Zoom': {'x': zoom}}
    ptz_service.ContinuousMove(request)
    time.sleep(0.05)
    ptz_service.Stop({'ProfileToken': profile.token})

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

# --- Stream Anzeige via GStreamer Low-Latency / Hardware-Decoding ---
def show_stream():
    global gst_proc
#    cmd = [
#        'gst-launch-1.0',
#        'rtspsrc', f'location={RTSP_URL}', 'latency=0',
#        '!', 'rtph264depay',
#        '!', 'h264parse',
##        '!', 'v4l2h264dec',    # Hardware-Decoding für Pi 5
#        '!', 'avdec_h264',
#        '!', 'videoconvert',
#        '!', 'autovideosink'
#    ]

    cmd = [
        'ffplay',
        '-fflags', 'nobuffer',
        '-flags', 'low_delay',
        '-framedrop',
        '-an',           # Audio ignorieren
        '-window_title', 'Kamera',
        RTSP_URL
    ]
    gst_proc = subprocess.Popen(cmd)
    gst_proc.wait()

# --- Steuerungs-Loop für Joystick / Potentiometer ---
def control_loop():
    global running
    while running:
        x_val = apply_deadzone(read_stable_mcp(joy_x))
        y_val = apply_deadzone(read_stable_mcp(joy_y))
        zoom_val = apply_deadzone(read_stable_mcp(pot))
        btn = joy_btn.is_pressed

        # Werte in [-1,1] für PTZ
        x_ptz = (x_val - 0.5) * 2
        y_ptz = (y_val - 0.5) * 2
        zoom_ptz = (zoom_val - 0.5) * 2

        if abs(x_ptz) > 0.05 or abs(y_ptz) > 0.05 or abs(zoom_ptz) > 0.05:
            move_ptz(x_ptz, y_ptz, zoom_ptz)

        if btn:
            if not recording:
                start_recording()
        else:
            if recording:
                stop_recording()

        time.sleep(0.05)

# --- Main ---
if __name__ == "__main__":
    try:
        # Stream anzeigen (Low-Latency, Hardware-Decoding)
        t_stream = threading.Thread(target=show_stream, daemon=True)
        t_stream.start()

        # Steuerung starten
        t_control = threading.Thread(target=control_loop, daemon=True)
        t_control.start()

        # Hauptthread wartet, bis Stream beendet
        while t_stream.is_alive():
            time.sleep(0.1)

    except KeyboardInterrupt:
        running = False
        stop_recording()
        if gst_proc is not None:
            gst_proc.terminate()
        print("Beendet.")
