import os
os.environ["QT_QPA_PLATFORM"] = "xcb"
import cv2
import lgpio
import time
import subprocess
from onvif import ONVIFCamera
import numpy as np
import threading

# --- Kamera-Zugangsdaten ---
CAMERA_IP = '192.168.178.122'
CAMERA_PORT = 8899
USERNAME = 'admin'
PASSWORD = ''
RTSP_URL = f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/stream"
#RTSP_URL = f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:80/ch0_1.264"

# --- GPIO-Pins ---
JOYSTICK_X = 17  # z.B. analoger Joystick X an ADC, hier als Beispiel GPIO17
JOYSTICK_Y = 27  # analoger Joystick Y an ADC, hier als Beispiel GPIO27
ZOOM_POT = 22    # Potentiometer für Zoom (ADC, hier als Beispiel GPIO22)
BUTTON = 23      # Aufnahme-Button

frame = None
frame_lock = threading.Lock()
recording = False

# GPIO-Handle für lgpio
gpio_handle = None

# --- Button-Koordinaten (x1, y1, x2, y2) ---
BUTTONS = {
    "start": (20, 400, 170, 470),
    "stop": (200, 400, 350, 470)
}

# --- Setup ---
def setup_gpio():
    global gpio_handle
    gpio_handle = lgpio.gpiochip_open(0)  # GPIO-Chip 0 öffnen
    lgpio.gpio_claim_input(gpio_handle, BUTTON, lgpio.SET_PULL_UP)

def cleanup_gpio():
    global gpio_handle
    if gpio_handle is not None:
        lgpio.gpiochip_close(gpio_handle)

def read_button():
    if gpio_handle is not None:
        return lgpio.gpio_read(gpio_handle, BUTTON) == 0  # LOW = gedrückt
    return False

def read_joystick():
    # Hier ADC-Code einfügen, Rückgabe: x, y im Bereich -1.0 bis 1.0
    return 0.0, 0.0

def read_zoom():
    # Hier ADC-Code einfügen, Rückgabe: zoom im Bereich -1.0 bis 1.0
    return 0.0

# --- PTZ Kamera Setup ---
cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
media_service = cam.create_media_service()
ptz_service = cam.create_ptz_service()
profiles = media_service.GetProfiles()
profile = profiles[0]

def ptz_loop():
    global recording
    while True:
        x, y = read_joystick()
        zoom = read_zoom()
        if abs(x) > 0.1 or abs(y) > 0.1 or abs(zoom) > 0.1:
            move_ptz(x, y, zoom)

        if read_button():
            if not recording:
                start_recording()
                recording = True
        else:
            if recording:
                stop_recording()
                recording = False
        time.sleep(0.05)

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
    global ffmpeg_proc
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
        print(f"Aufnahme gestartet: {filename}")


def stop_recording():
    global ffmpeg_proc
    if ffmpeg_proc is not None:
        ffmpeg_proc.terminate()
        ffmpeg_proc.wait()
        print("Aufnahme gestoppt.")
        ffmpeg_proc = None

def draw_buttons(frame, recording):
    color_start = (0, 255, 0) if not recording else (100, 100, 100)
    color_stop = (0, 0, 255) if recording else (100, 100, 100)
    cv2.rectangle(frame, BUTTONS["start"][:2], BUTTONS["start"][2:], color_start, -1)
    cv2.rectangle(frame, BUTTONS["stop"][:2], BUTTONS["stop"][2:], color_stop, -1)
    cv2.putText(frame, "Start", (BUTTONS["start"][0]+20, BUTTONS["start"][1]+45), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,0), 2)
    cv2.putText(frame, "Stop", (BUTTONS["stop"][0]+30, BUTTONS["stop"][1]+45), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)

def point_in_rect(x, y, rect):
    x1, y1, x2, y2 = rect
    return x1 <= x <= x2 and y1 <= y <= y2

def stream_reader(rtsp_url):
    global frame
    cap = cv2.VideoCapture(rtsp_url)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    while True:
        ret, f = cap.read()
        if not ret:
            continue
        with frame_lock:
            frame = f.copy()

def show_preview():
    global frame, running
    window_name = "Kaderblick Verfolger"

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    while running:
        with frame_lock:
            f = frame.copy() if frame is not None else None
        if f is not None:
            h, w = f.shape[:2]
#            screen_w = cv2.getWindowImageRect(window_name)[2]
#            screen_h = cv2.getWindowImageRect(window_name)[3]
            screen_w=1280
            screen_h=800

            scale = min(screen_w / w, screen_h / h)
            new_w, new_h = int(w * scale), int(h * scale)
            resized = cv2.resize(f, (new_w, new_h), interpolation=cv2.INTER_AREA)

            # Hintergrund schwarz
            background = np.zeros((screen_h, screen_w, 3), dtype=np.uint8)
            y_off = (screen_h - new_h) // 2
            x_off = (screen_w - new_w) // 2
            background[y_off:y_off+new_h, x_off:x_off+new_w] = resized

            draw_buttons(background, recording)
            cv2.imshow(window_name, background)

        if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
            running = False

        if cv2.waitKey(1) & 0xFF == ord('q'):
            running = False
            break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    setup_gpio()
    global running
    # Starte Stream-Thread
    t_stream = threading.Thread(target=stream_reader, args=(RTSP_URL,), daemon=True)
    t_stream.start()
    # Starte Vorschau-Thread
    t_preview = threading.Thread(target=show_preview, daemon=True)
    t_preview.start()

    try:
        running = True
        while True:
            x, y = read_joystick()
            zoom = read_zoom()
            if abs(x) > 0.1 or abs(y) > 0.1 or abs(zoom) > 0.1:
                move_ptz(x, y, zoom)
            else:
                ptz_service.Stop({'ProfileToken': profile.token})
            time.sleep(0.05)
    except KeyboardInterrupt:
        cleanup_gpio()
        stop_recording()
        print("Beendet.")
