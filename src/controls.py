"""
Steuerungs-Loop — Joystick, Poti, Button → PTZ / Aufnahme.

Einfach & direkt:
  - ONVIF-Calls dauern nur ~20ms → direkte Aufrufe, kein Worker-Thread
  - Auto-Kalibrierung der Joystick-Ruheposition beim Start
  - Deadzone bezogen auf kalibrierte Mitte (nicht fest 0.5)
  - Zoom: Poti steuert **absolute** Zoom-Position (0%–100%)
  - PT: Joystick steuert Geschwindigkeit (ContinuousMove)
  - Zoom und PT sind unabhängig (AbsoluteMove vs. ContinuousMove)
"""

import time

from src import hardware as hw
from src import onvif_ptz as ptz
from src import recording
import src.state as state
from config.config import (
    PAN_MAX, TILT_MAX,
    DEADZONE,
    LOOP_SLEEP,
)

# ── Konstanten ────────────────────────────────────────────────
_CHANGE_THRESH = 0.04     # Mindest-Änderung für neuen Move-Befehl
_ZOOM_THRESH   = 0.02     # Mindest-Änderung für neuen AbsoluteZoom-Befehl
_RESEND_INTERVAL = 1.0    # ContinuousMove alle 1s wiederholen (Sicherheit)
_CALIBRATION_SAMPLES = 30  # Anzahl Samples für Auto-Kalibrierung
_DEBUG = True              # Debug-Ausgaben an/aus


def _calibrate():
    """
    Liest N Samples im Ruhezustand und bestimmt die Joystick-Mittelposition.
    MUSS bei Programmstart aufgerufen werden (Joystick NICHT BERÜHREN!).
    Poti wird nicht kalibriert — Absolutwert wird direkt als Zoom-Position genutzt.
    """
    print("  Kalibriere Joystick (NICHT BERÜHREN!) ...", flush=True)
    sx, sy = 0.0, 0.0
    for _ in range(_CALIBRATION_SAMPLES):
        sx += hw.joy_x.value
        sy += hw.joy_y.value
        time.sleep(0.02)

    cx = sx / _CALIBRATION_SAMPLES
    cy = sy / _CALIBRATION_SAMPLES

    print(f"  Kalibriert: X={cx:.4f}  Y={cy:.4f}")
    print(f"  Zoom-Poti: Absolutmodus (Wert={hw.pot.value:.2f} → {hw.pot.value*100:.0f}%)")
    return cx, cy


def _apply_deadzone(value, deadzone):
    """Wendet Deadzone an und skaliert den Rest auf 0.0-1.0."""
    if abs(value) <= deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    scaled = (abs(value) - deadzone) / (1.0 - deadzone)
    return sign * min(scaled, 1.0)


def control_loop():
    """Hauptschleife: liest Hardware ein und steuert PTZ + Aufnahme."""

    # Auto-Kalibrierung (nur Joystick, Poti ist absolut)
    center_x, center_y = _calibrate()

    btn_last_state = False
    btn_press_time = None
    btn_action_done = False

    # PT-Zustand (Pan/Tilt via ContinuousMove)
    pt_moving = False
    last_pan = 0.0
    last_tilt = 0.0
    last_pt_cmd_time = 0.0

    # Zoom-Zustand (Absolut via AbsoluteMove — unabhängig von PT)
    last_zoom_pos = -1.0   # Initialer Wert erzwingt erstes Setzen

    print("  Steuerung aktiv.\n")

    while state.running:
        try:
            # ── Hardware einlesen ─────────────────────────────
            raw_x = hw.joy_x.value
            raw_y = hw.joy_y.value
            raw_z = hw.pot.value      # 0.0 – 1.0 → direkt Zoom-Position

            # Joystick: Relativ zur kalibrierten Mitte (-1.0 bis +1.0)
            rel_x = (raw_x - center_x) * 2.0
            rel_y = (raw_y - center_y) * 2.0

            # Deadzone + Skalierung (nur Joystick)
            pan  = _apply_deadzone(rel_x, DEADZONE) * PAN_MAX
            tilt = _apply_deadzone(rel_y, DEADZONE) * TILT_MAX

            now = time.time()

            # ── Zoom (AbsoluteMove — unabhängig von PT) ──────
            zoom_pos = max(0.0, min(1.0, raw_z))
            if abs(zoom_pos - last_zoom_pos) > _ZOOM_THRESH:
                ptz.absolute_zoom(zoom_pos)
                if _DEBUG:
                    print(f"  🔍 ZOOM → {zoom_pos*100:.0f}%")
                last_zoom_pos = zoom_pos

            # ── Pan/Tilt (ContinuousMove — unabhängig von Zoom) ─
            pt_active = (pan != 0.0 or tilt != 0.0)

            if pt_active:
                value_changed = (
                    abs(pan - last_pan) > _CHANGE_THRESH or
                    abs(tilt - last_tilt) > _CHANGE_THRESH
                )
                needs_resend = (now - last_pt_cmd_time) > _RESEND_INTERVAL

                if not pt_moving or value_changed or needs_resend:
                    ptz.continuous_move(pan, tilt, 0)
                    last_pt_cmd_time = time.time()
                    if _DEBUG and (not pt_moving or value_changed):
                        print(f"  → PT pan={pan:+.3f} tilt={tilt:+.3f}")
                    last_pan = pan
                    last_tilt = tilt
                    pt_moving = True

            elif pt_moving:
                ptz.stop()
                last_pt_cmd_time = now
                pt_moving = False
                last_pan = 0.0
                last_tilt = 0.0
                if _DEBUG:
                    print("  ■ PT STOP")

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
