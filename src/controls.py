"""
Steuerungs-Loop — Joystick, Poti, Button → PTZ / Aufnahme.
"""

import time

from src import hardware as hw
from src import onvif_ptz as ptz
from src import recording
import src.state as state
from config.config import (
    PAN_MAX, TILT_MAX, ZOOM_MAX,
    DEADZONE, ZOOM_DEADZONE_LO, ZOOM_DEADZONE_HI,
    LOOP_SLEEP,
)


def control_loop():
    """Hauptschleife: liest Hardware ein und steuert PTZ + Aufnahme."""
    btn_last_state = False
    btn_press_time = None
    btn_action_done = False

    prev_moving = False
    prev_pan = 0.0
    prev_tilt = 0.0
    prev_zoom = 0.0
    change_threshold = 0.03

    while state.running:
        try:
            # ── Joystick / Poti einlesen ─────────────────────
            raw_x = hw.joy_x.value
            raw_y = hw.joy_y.value
            raw_z = int(hw.pot.value * 1023)

            pan  = (raw_x * 2.0 - 1.0) * PAN_MAX
            tilt = (raw_y * 2.0 - 1.0) * TILT_MAX

            if abs(pan) < DEADZONE:
                pan = 0.0
            if abs(tilt) < DEADZONE:
                tilt = 0.0

            zoom_speed = 0.0
            if raw_z < ZOOM_DEADZONE_LO:
                zoom_speed = -(ZOOM_DEADZONE_LO - raw_z) / ZOOM_DEADZONE_LO * ZOOM_MAX
            elif raw_z > ZOOM_DEADZONE_HI:
                zoom_speed = (raw_z - ZOOM_DEADZONE_HI) / (1023 - ZOOM_DEADZONE_HI) * ZOOM_MAX

            # ── PTZ nur bei Änderung senden ──────────────────
            is_moving = (pan != 0.0 or tilt != 0.0 or zoom_speed != 0.0)

            if is_moving:
                value_changed = (
                    abs(pan - prev_pan) > change_threshold or
                    abs(tilt - prev_tilt) > change_threshold or
                    abs(zoom_speed - prev_zoom) > change_threshold
                )
                if not prev_moving or value_changed:
                    ptz.continuous_move(pan, tilt, zoom_speed)
                    prev_pan = pan
                    prev_tilt = tilt
                    prev_zoom = zoom_speed
            elif prev_moving:
                ptz.stop()

            prev_moving = is_moving

            # ── Button (kurz=Screenshot, lang=Aufnahme) ──────
            btn_state = hw.joy_btn.is_pressed
            now = time.time()

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
            # SPI-Fehler, ONVIF-Timeout etc. dürfen den Loop NICHT killen!
            print(f"  ⚠ Control-Loop Fehler (weiter): {e}")

        time.sleep(LOOP_SLEEP)
