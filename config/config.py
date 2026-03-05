"""
Konfiguration — alle Konstanten an einem Ort.
Hier ändern, nirgendwo sonst.
"""

import os

# ── Kamera ────────────────────────────────────────────────────
CAMERA_IP   = '192.168.178.122'
CAMERA_PORT = 8899           # ONVIF-Port
USERNAME    = 'admin'
PASSWORD    = ''

# ── RTSP-Streams ─────────────────────────────────────────────
RTSP_MAIN = f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/stream"
RTSP_SUB  = f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/stream2"

# ── Aufnahme ─────────────────────────────────────────────────
RECORDING_DIR = os.path.expanduser("~/Aufnahmen")
os.makedirs(RECORDING_DIR, exist_ok=True)

# ── GPIO / ADC (MCP3008 über SPI) ────────────────────────────
BTN_PIN = 17

# ── PTZ-Einstellungen ────────────────────────────────────────
PAN_MAX  = 1.0
TILT_MAX = 1.0
ZOOM_MAX = 1.0
DEADZONE = 0.12              # Joystick-Deadzone (relativ zu kalibrierter Mitte)
ZOOM_DEADZONE = 0.30         # Zoom-Poti-Deadzone (breit, damit leichtes Berühren nicht zoomt)
LOOP_SLEEP = 0.05            # 20 Hz Steuer-Loop

# ── AI-Watchdog ──────────────────────────────────────────────
AI_CHECK_INTERVAL = 30       # Sekunden zwischen den Checks
