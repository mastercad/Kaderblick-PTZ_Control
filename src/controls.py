"""
Steuerungs-Loop — Joystick, Poti, Button → PTZ / Aufnahme.

Nicht-blockierende ONVIF-Befehle + Input-Smoothing für reaktive Steuerung.
"""

import time
import threading

from src import hardware as hw
from src import onvif_ptz as ptz
from src import recording
import src.state as state
from config.config import (
    PAN_MAX, TILT_MAX, ZOOM_MAX,
    DEADZONE, ZOOM_DEADZONE_LO, ZOOM_DEADZONE_HI,
    LOOP_SLEEP,
)

# ── Smoothing & Deadzone ─────────────────────────────────────
_EMA_ALPHA    = 0.4      # Exponential Moving Average (0.0=glatt, 1.0=roh)
_HYSTERESIS   = 0.03     # Deadzone-Hysterese: Wert muss DEADZONE+HYSTERESIS
                          # überschreiten bevor Bewegung startet
_CHANGE_THRESH = 0.05    # Mindest-Änderung bevor neuer Move-Befehl gesendet wird


# ── Nicht-blockierende PTZ-Befehle ──────────────────────────
# ONVIF SOAP-Calls können 26-200ms dauern und würden den Loop blockieren.
# Deshalb: Fire-and-forget in Worker-Thread.
_ptz_lock = threading.Lock()
_ptz_pending = None       # (typ, pan, tilt, zoom) oder ("stop",)


def _ptz_worker():
    """Background-Worker: sendet den jeweils LETZTEN PTZ-Befehl."""
    global _ptz_pending
    while state.running:
        cmd = None
        with _ptz_lock:
            if _ptz_pending is not None:
                cmd = _ptz_pending
                _ptz_pending = None

        if cmd is not None:
            try:
                if cmd[0] == "move":
                    ptz.continuous_move(cmd[1], cmd[2], cmd[3])
                elif cmd[0] == "stop":
                    ptz.stop()
            except Exception as e:
                print(f"  ⚠ PTZ-Worker Fehler: {e}")
        else:
            time.sleep(0.01)  # 10ms idle-sleep wenn nichts zu tun


def _send_move(pan, tilt, zoom):
    """Nicht-blockierend: queut einen ContinuousMove-Befehl."""
    global _ptz_pending
    with _ptz_lock:
        _ptz_pending = ("move", pan, tilt, zoom)


def _send_stop():
    """Nicht-blockierend: queut einen Stop-Befehl."""
    global _ptz_pending
    with _ptz_lock:
        _ptz_pending = ("stop",)


def _apply_deadzone(value, was_active):
    """Deadzone mit Hysterese: verhindert Jitter am Rand."""
    threshold = DEADZONE if was_active else (DEADZONE + _HYSTERESIS)
    if abs(value) < threshold:
        return 0.0, False
    return value, True


def control_loop():
    """Hauptschleife: liest Hardware ein und steuert PTZ + Aufnahme."""

    # PTZ-Worker starten
    worker = threading.Thread(target=_ptz_worker, daemon=True)
    worker.start()

    btn_last_state = False
    btn_press_time = None
    btn_action_done = False

    prev_moving = False
    prev_pan = 0.0
    prev_tilt = 0.0
    prev_zoom = 0.0

    # EMA-Zustand
    ema_x = 0.5    # MCP3008 liefert 0.0-1.0, Mitte = 0.5
    ema_y = 0.5
    ema_z = 512.0  # Poti-Mitte

    # Hysterese-Zustand
    pan_active = False
    tilt_active = False

    stop_sent_count = 0
    _STOP_REPEAT = 3

    while state.running:
        try:
            # ── Joystick / Poti einlesen + Glätten ───────────
            ema_x = _EMA_ALPHA * hw.joy_x.value + (1 - _EMA_ALPHA) * ema_x
            ema_y = _EMA_ALPHA * hw.joy_y.value + (1 - _EMA_ALPHA) * ema_y
            ema_z = _EMA_ALPHA * (hw.pot.value * 1023) + (1 - _EMA_ALPHA) * ema_z

            raw_pan  = (ema_x * 2.0 - 1.0) * PAN_MAX
            raw_tilt = (ema_y * 2.0 - 1.0) * TILT_MAX

            pan, pan_active   = _apply_deadzone(raw_pan, pan_active)
            tilt, tilt_active = _apply_deadzone(raw_tilt, tilt_active)

            raw_z = int(ema_z)
            zoom_speed = 0.0
            if raw_z < ZOOM_DEADZONE_LO:
                zoom_speed = -(ZOOM_DEADZONE_LO - raw_z) / ZOOM_DEADZONE_LO * ZOOM_MAX
            elif raw_z > ZOOM_DEADZONE_HI:
                zoom_speed = (raw_z - ZOOM_DEADZONE_HI) / (1023 - ZOOM_DEADZONE_HI) * ZOOM_MAX

            # ── PTZ-Befehle (nicht-blockierend) ──────────────
            is_moving = (pan != 0.0 or tilt != 0.0 or zoom_speed != 0.0)

            if is_moving:
                stop_sent_count = 0
                value_changed = (
                    abs(pan - prev_pan) > _CHANGE_THRESH or
                    abs(tilt - prev_tilt) > _CHANGE_THRESH or
                    abs(zoom_speed - prev_zoom) > _CHANGE_THRESH
                )
                if not prev_moving or value_changed:
                    _send_move(pan, tilt, zoom_speed)
                    prev_pan = pan
                    prev_tilt = tilt
                    prev_zoom = zoom_speed
            elif prev_moving or stop_sent_count < _STOP_REPEAT:
                if prev_moving:
                    stop_sent_count = 0
                if stop_sent_count < _STOP_REPEAT:
                    _send_stop()
                    stop_sent_count += 1

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
            print(f"  ⚠ Control-Loop Fehler (weiter): {e}")

        time.sleep(LOOP_SLEEP)
