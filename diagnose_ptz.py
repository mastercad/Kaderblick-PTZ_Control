#!/usr/bin/env python3
"""
ONVIF PTZ Diagnose — testet wie die Kamera auf Befehle reagiert.

Testet:
  1. Wie schnell reagiert ContinuousMove?
  2. Kommt Stop zuverlässig an?
  3. Hat ContinuousMove ein Auto-Timeout (Kamera stoppt von allein)?
  4. Müssen Move-Befehle periodisch wiederholt werden?
"""

import time
import sys

sys.path.insert(0, '.')
from onvif import ONVIFCamera
from config.config import CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD


def connect():
    print(f"Verbinde mit {CAMERA_IP}:{CAMERA_PORT} ...")
    cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
    media = cam.create_media_service()
    ptz_svc = cam.create_ptz_service()
    profile = media.GetProfiles()[0]
    move_req = ptz_svc.create_type('ContinuousMove')
    move_req.ProfileToken = profile.token
    stop_req = {'ProfileToken': profile.token}
    print(f"Verbunden. Profil: {profile.Name}\n")
    return ptz_svc, move_req, stop_req


def timed_move(ptz_svc, move_req, pan, tilt, zoom=0.0):
    move_req.Velocity = {
        'PanTilt': {'x': float(pan), 'y': float(tilt)},
        'Zoom': {'x': float(zoom)}
    }
    t0 = time.time()
    ptz_svc.ContinuousMove(move_req)
    dt = (time.time() - t0) * 1000
    return dt


def timed_stop(ptz_svc, stop_req):
    t0 = time.time()
    ptz_svc.Stop(stop_req)
    dt = (time.time() - t0) * 1000
    return dt


def main():
    ptz_svc, move_req, stop_req = connect()

    # ── Test 1: Move/Stop Latenz ──────────────────────────────
    print("=" * 60)
    print("TEST 1: Move/Stop Latenz (10 Zyklen)")
    print("=" * 60)
    move_times = []
    stop_times = []
    for i in range(10):
        mt = timed_move(ptz_svc, move_req, 0.5, 0.0)
        time.sleep(0.1)
        st = timed_stop(ptz_svc, stop_req)
        time.sleep(0.2)
        move_times.append(mt)
        stop_times.append(st)
        print(f"  Zyklus {i+1:2d}: Move={mt:6.1f}ms  Stop={st:6.1f}ms")

    print(f"\n  Move: min={min(move_times):.0f}ms  max={max(move_times):.0f}ms  avg={sum(move_times)/len(move_times):.0f}ms")
    print(f"  Stop: min={min(stop_times):.0f}ms  max={max(stop_times):.0f}ms  avg={sum(stop_times)/len(stop_times):.0f}ms")

    # ── Test 2: ContinuousMove Timeout ────────────────────────
    print()
    print("=" * 60)
    print("TEST 2: ContinuousMove Timeout")
    print("  Sende EINEN Move-Befehl (pan rechts, speed 0.3)")
    print("  Beobachte ob die Kamera von allein stoppt!")
    print("  Abbruch mit Ctrl+C")
    print("=" * 60)

    mt = timed_move(ptz_svc, move_req, 0.3, 0.0)
    print(f"  Move gesendet ({mt:.0f}ms). Kamera sollte sich jetzt bewegen...")
    print(f"  Warte... (Ctrl+C wenn Kamera aufhört sich zu bewegen)")

    try:
        start = time.time()
        while True:
            elapsed = time.time() - start
            print(f"\r  Läuft seit {elapsed:.1f}s ...", end="", flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        elapsed = time.time() - start
        st = timed_stop(ptz_svc, stop_req)
        print(f"\n\n  Kamera lief {elapsed:.1f}s bevor Ctrl+C")
        print(f"  Stop gesendet ({st:.0f}ms)")

        if elapsed < 5:
            print("\n  ⚠ KAMERA HAT AUTO-TIMEOUT!")
            print("    → ContinuousMove muss periodisch wiederholt werden!")
        else:
            print("\n  ✓ Kamera lief >5s → kein Auto-Timeout erkannt")

    # ── Test 3: Schnelle Move-Wechsel ─────────────────────────
    print()
    print("=" * 60)
    print("TEST 3: Schnelle Richtungswechsel (links/rechts)")
    print("=" * 60)
    for i in range(6):
        direction = 0.5 if i % 2 == 0 else -0.5
        label = "RECHTS" if direction > 0 else "LINKS"
        mt = timed_move(ptz_svc, move_req, direction, 0.0)
        print(f"  {label}: {mt:.0f}ms")
        time.sleep(1.0)

    st = timed_stop(ptz_svc, stop_req)
    print(f"  STOP: {st:.0f}ms")

    # ── Test 4: Stop-Zuverlässigkeit ──────────────────────────
    print()
    print("=" * 60)
    print("TEST 4: Stop-Zuverlässigkeit (Move → sofort Stop)")
    print("=" * 60)
    for i in range(5):
        mt = timed_move(ptz_svc, move_req, 0.5, 0.0)
        st = timed_stop(ptz_svc, stop_req)
        print(f"  Zyklus {i+1}: Move={mt:.0f}ms → Stop={st:.0f}ms (kein Delay)")
        time.sleep(0.5)

    print()
    print("FERTIG. Bitte gesamte Ausgabe kopieren und teilen!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAbgebrochen.")
    except Exception as e:
        print(f"\nFEHLER: {e}")
        import traceback
        traceback.print_exc()
