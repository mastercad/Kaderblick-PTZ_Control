"""
Steuerungs-Loop — Joystick, Poti, Button → PTZ / Aufnahme.

Einfach & direkt:
  - ONVIF-Calls dauern nur ~20ms → direkte Aufrufe, kein Worker-Thread
  - Auto-Kalibrierung der Joystick/Poti-Ruheposition beim Start
  - Deadzone bezogen auf kalibrierte Mitte (nicht fest 0.5)
  - Periodisches Re-Send als Sicherheit
  - Debug-Ausgabe zum Nachvollziehen
"""

import time

from src import hardware as hw
from src import onvif_ptz as ptz
from src import recording
import src.state as state
from config.config import (
    PAN_MAX, TILT_MAX, ZOOM_MAX,
    DEADZONE, ZOOM_DEADZONE,
    LOOP_SLEEP,
)

# ── Konstanten ────────────────────────────────────────────────
_CHANGE_THRESH = 0.04     # Mindest-Änderung für neuen Move-Befehl
_RESEND_INTERVAL = 1.0    # ContinuousMove alle 1s wiederholen (Sicherheit)
_CALIBRATION_SAMPLES = 30  # Anzahl Samples für Auto-Kalibrierung
_DEBUG = True              # Debug-Ausgaben an/aus


def _calibrate():
    """
    Liest N Samples im Ruhezustand und bestimmt die Mittelposition.
    MUSS bei Programmstart aufgerufen werden (Joystick/Poti nicht berühren!).
    """
    print("  Kalibriere Joystick/Poti (NICHT BERÜHREN!) ...", flush=True)
    sx, sy, sz = 0.0, 0.0, 0.0
    for _ in range(_CALIBRATION_SAMPLES):
        sx += hw.joy_x.value
        sy += hw.joy_y.value
        sz += hw.pot.value
        time.sleep(0.02)

    cx = sx / _CALIBRATION_SAMPLES
    cy = sy / _CALIBRATION_SAMPLES
    cz = sz / _CALIBRATION_SAMPLES

    print(f"  Kalibriert: X={cx:.4f}  Y={cy:.4f}  Zoom={cz:.4f}")
    return cx, cy, cz


def _apply_deadzone(value, deadzone):
    """Wendet Deadzone an und skaliert den Rest auf 0.0-1.0."""
    if abs(value) <= deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    scaled = (abs(value) - deadzone) / (1.0 - deadzone)
    scaled = min(scaled, 1.0)
    # Quadratische Kurve: kleine Auslenkung = sehr langsam, volle = voll
    scaled = scaled * scaled
    return sign * scaled


def control_loop():
    """Hauptschleife: liest Hardware ein und steuert PTZ + Aufnahme."""

    # Auto-Kalibrierung
    center_x, center_y, center_z = _calibrate()

    btn_last_state = False
    btn_press_time = None
    btn_action_done = False

    # PTZ-Zustand
    currently_moving = False
    last_pan = 0.0
    last_tilt = 0.0
    last_zoom = 0.0
    last_cmd_time = 0.0

    print("  Steuerung aktiv.\n")

    while state.running:
        try:
            # ── Hardware einlesen ─────────────────────────────
            raw_x = hw.joy_x.value
            raw_y = hw.joy_y.value
            raw_z = hw.pot.value

            # Relativ zur kalibrierten Mitte (-1.0 bis +1.0)
            rel_x = (raw_x - center_x) * 2.0
            rel_y = (raw_y - center_y) * 2.0
            rel_z = (raw_z - center_z) * -2.0

            # Deadzone + Skalierung
            pan  = _apply_deadzone(rel_x, DEADZONE) * PAN_MAX
            tilt = _apply_deadzone(rel_y, DEADZONE) * TILT_MAX
            zoom = _apply_deadzone(rel_z, ZOOM_DEADZONE) * ZOOM_MAX

            # ── PTZ-Logik (direkt, kein Worker) ──────────────
            now = time.time()
            want_move = (pan != 0.0 or tilt != 0.0 or zoom != 0.0)

            if want_move:
                value_changed = (
                    abs(pan - last_pan) > _CHANGE_THRESH or
                    abs(tilt - last_tilt) > _CHANGE_THRESH or
                    abs(zoom - last_zoom) > _CHANGE_THRESH
                )
                needs_resend = (now - last_cmd_time) > _RESEND_INTERVAL

                if not currently_moving or value_changed or needs_resend:
                    ptz.continuous_move(pan, tilt, zoom)
                    last_cmd_time = now
                    if _DEBUG and (not currently_moving or value_changed):
                        print(f"  → MOVE pan={pan:+.3f} tilt={tilt:+.3f} zoom={zoom:+.3f}")
                    last_pan = pan
                    last_tilt = tilt
                    last_zoom = zoom
                    currently_moving = True

            elif currently_moving:
                ptz.stop()
                last_cmd_time = now
                currently_moving = False
                last_pan = 0.0
                last_tilt = 0.0
                last_zoom = 0.0
                if _DEBUG:
                    print("  ■ STOP")

            # ── Button (kurz=Screenshot, lang=Aufnahme) ──────
            btn_state = hw.joy_btn.is_pressed

            if btn_state and not btn_last_state:
                btn_press_time = now
                btn_action_done = False
            elif btn_state and btn_press_time is not None:
                if not btn_action_done and now - btn_press_time > 3.0:
                    if not state.recording:
                        recording.start()
                    else:
                        recording.stop()
                    btn_action_done = True
            elif not btn_state and btn_last_state:
                if btn_press_time is not None and not btn_action_done:
                    if now - btn_press_time < 3.0:
                        recording.take_screenshot()
                btn_press_time = None
                btn_action_done = False

            btn_last_state = btn_state

        except Exception as e:
            print(f"  ⚠ Control-Loop Fehler (weiter): {e}")

        time.sleep(LOOP_SLEEP)
