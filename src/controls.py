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

# Rate-Limiting: mindestens so viele Sekunden zwischen ONVIF-Befehlen
_MIN_CMD_INTERVAL = 0.10   # 100 ms → max ~10 Befehle/s


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
    last_cmd_time = 0.0
    stop_retries = 0          # Zählt wiederholte Stop-Befehle
    _STOP_RETRY_MAX = 3       # So oft Stop wiederholen nach Bewegungsende

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

            # ── PTZ mit Rate-Limiting senden ─────────────────
            now = time.time()
            is_moving = (pan != 0.0 or tilt != 0.0 or zoom_speed != 0.0)

            if is_moving:
                stop_retries = 0
                value_changed = (
                    abs(pan - prev_pan) > change_threshold or
                    abs(tilt - prev_tilt) > change_threshold or
                    abs(zoom_speed - prev_zoom) > change_threshold
                )
                if (not prev_moving or value_changed) and \
                   (now - last_cmd_time >= _MIN_CMD_INTERVAL):
                    ptz.continuous_move(pan, tilt, zoom_speed)
                    last_cmd_time = now
                    prev_pan = pan
                    prev_tilt = tilt
                    prev_zoom = zoom_speed
            elif prev_moving or stop_retries > 0:
                # Stop MEHRFACH senden damit kein Befehl verloren geht
                if prev_moving:
                    stop_retries = _STOP_RETRY_MAX
                if stop_retries > 0 and (now - last_cmd_time >= _MIN_CMD_INTERVAL):
                    ptz.stop()
                    last_cmd_time = now
                    stop_retries -= 1

            prev_moving = is_moving

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
            # SPI-Fehler, ONVIF-Timeout etc. dürfen den Loop NICHT killen!
            print(f"  ⚠ Control-Loop Fehler (weiter): {e}")

        time.sleep(LOOP_SLEEP)
