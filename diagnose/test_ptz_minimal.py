#!/usr/bin/env python3
"""
MINIMAL PTZ-Test: Joystick → Kamera. Kein Threading, kein Smoothing.
Zeigt JEDE Entscheidung. Beenden mit Ctrl+C.
"""

import time
import sys

sys.path.insert(0, '.')

from gpiozero import MCP3008
from onvif import ONVIFCamera
from config.config import CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD

DEADZONE = 0.12

# ── Hardware ──────────────────────────────────────────────────
print("MCP3008 init...", flush=True)
joy_x = MCP3008(channel=3)
joy_y = MCP3008(channel=2)
print("  OK")

# ── ONVIF ─────────────────────────────────────────────────────
print(f"ONVIF init ({CAMERA_IP}:{CAMERA_PORT})...", flush=True)
cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
media = cam.create_media_service()
ptz_svc = cam.create_ptz_service()
profile = media.GetProfiles()[0]
move_req = ptz_svc.create_type('ContinuousMove')
move_req.ProfileToken = profile.token
stop_req = {'ProfileToken': profile.token}
print("  OK")

# ── Kalibrierung ─────────────────────────────────────────────
print("Kalibriere (JOYSTICK LOSLASSEN!)...", flush=True)
sx, sy = 0.0, 0.0
for _ in range(20):
    sx += joy_x.value
    sy += joy_y.value
    time.sleep(0.02)
cx = sx / 20
cy = sy / 20
print(f"  Mitte: X={cx:.4f}  Y={cy:.4f}")

# ── Loop ──────────────────────────────────────────────────────
print()
print("Bereit! Joystick bewegen. Ctrl+C zum Beenden.")
print(f"Deadzone: {DEADZONE}")
print("-" * 70)

moving = False
loop_count = 0

try:
    while True:
        rx = joy_x.value
        ry = joy_y.value

        pan  = (rx - cx) * 2.0
        tilt = (ry - cy) * 2.0

        if abs(pan) < DEADZONE:
            pan = 0.0
        if abs(tilt) < DEADZONE:
            tilt = 0.0

        want_move = (pan != 0.0 or tilt != 0.0)

        # Jede Sekunde: Status anzeigen (auch wenn nichts passiert)
        loop_count += 1
        if loop_count % 20 == 0:
            status = "MOVING" if moving else "IDLE"
            print(f"  [{status:6s}] raw=({rx:.4f},{ry:.4f}) pan={pan:+.3f} tilt={tilt:+.3f}", flush=True)

        if want_move and not moving:
            # Starten
            move_req.Velocity = {
                'PanTilt': {'x': float(pan), 'y': float(tilt)},
                'Zoom': {'x': 0.0}
            }
            t0 = time.time()
            ptz_svc.ContinuousMove(move_req)
            dt = (time.time() - t0) * 1000
            print(f"  >>> MOVE pan={pan:+.3f} tilt={tilt:+.3f} ({dt:.0f}ms)", flush=True)
            moving = True

        elif want_move and moving:
            # Richtung ändern (nur bei großer Änderung)
            pass  # Erstmal einfach weiterlaufen lassen

        elif not want_move and moving:
            # Stoppen
            t0 = time.time()
            ptz_svc.Stop(stop_req)
            dt = (time.time() - t0) * 1000
            print(f"  <<< STOP ({dt:.0f}ms)", flush=True)
            moving = False

        time.sleep(0.05)

except KeyboardInterrupt:
    if moving:
        ptz_svc.Stop(stop_req)
        print("\n  STOP gesendet.")
    print("\nBeendet.")
