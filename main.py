#!/usr/bin/env python3
"""
PTZ-Steuerung für Hiseeu HD118-PZ — Fußball-Aufnahme
=====================================================
Steuerung:
  - Joystick X/Y    → Pan/Tilt
  - Poti (CH0)      → Zoom
  - Button kurz     → Screenshot
  - Button lang 3s  → Aufnahme Start/Stop

Modulstruktur:
  src/config.py       Konstanten (IP, Ports, Schwellwerte)
  src/state.py        Geteilter Zustand (Globals)
  src/hardware.py     GPIO/ADC (MCP3008, Button)
  src/xm_protocol.py  XM Binary Protocol (Port 34567)
  src/ai_tracking.py  AI-Erkennung, Deaktivierung, Watchdog
  src/onvif_ptz.py    ONVIF PTZ + Auto-Reconnect
  src/overlay.py      Bildschirm-Overlay
  src/recording.py    Aufnahme + Screenshot
  src/stream.py       Live-Vorschau (mpv)
  src/controls.py     Steuerungs-Loop
"""

import sys
import time
import signal
import threading

import src.state as state
from src import onvif_ptz as ptz
from src import ai_tracking
from src import recording
from src import stream
from src import overlay
from src import controls
from config.config import AI_CHECK_INTERVAL


# ── Sauberes Beenden ─────────────────────────────────────────
def cleanup(signum=None, frame=None):
    state.running = False
    print("\nBeende...")
    recording.stop()
    if state.stream_proc is not None:
        state.stream_proc.terminate()
    ptz.stop()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


# ── Main ─────────────────────────────────────────────────────
if __name__ == "__main__":
    # ONVIF initialisieren
    ptz.init()

    # AI prüfen und deaktivieren
    print("Prüfe AI-Tracking Status...")
    try:
        was_active, count, still_active, still_details = ai_tracking.ensure_disabled()
    except Exception as e:
        print(f"  ⚠ Fehler bei AI-Prüfung: {e}")
        was_active, count, still_active, still_details = None, 0, None, []

    if was_active is None:
        print("  ⚠ Konnte AI-Status nicht prüfen (Verbindungsfehler)")
        print("    → Versuche trotzdem blind zu deaktivieren...")
        count = ai_tracking.disable()
        if count > 0:
            print(f"  ✓ {count} Feature(s) deaktiviert")
        else:
            print("  ⚠ Deaktivierung fehlgeschlagen")
            print("    → Ggf. manuell über iCSee/XMEye App deaktivieren")
    elif was_active:
        print(f"  🚨 AI-Tracking war AKTIV → {count} Feature(s) deaktiviert")
        if still_active:
            print(f"  ⚠ WARNUNG: AI immer noch aktiv: {', '.join(still_details)}")
            state.ai_warning_active = True
        elif still_active is False:
            print("  ✓ AI-Tracking erfolgreich deaktiviert")
        else:
            print("  ⚠ Verifikation fehlgeschlagen, Status unklar")
    else:
        print("  ✓ AI-Tracking ist AUS — alles gut!")

    # Threads starten
    print()
    print("Starte PTZ-Steuerung...")
    print("  Joystick → Pan/Tilt")
    print("  Poti     → Zoom")
    print("  Button kurz  → Screenshot")
    print("  Button 3s    → Aufnahme Start/Stop")
    print(f"  AI-Watchdog   → prüft alle {AI_CHECK_INTERVAL}s")
    print()

    t_stream   = threading.Thread(target=stream.show, daemon=True)
    t_control  = threading.Thread(target=controls.control_loop, daemon=True)
    t_watchdog = threading.Thread(target=ai_tracking.watchdog_loop, daemon=True)

    t_stream.start()
    t_control.start()
    t_watchdog.start()

    if state.ai_warning_active:
        overlay.ensure_running()

    # Warten bis Stream-Fenster geschlossen wird
    try:
        while t_stream.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass

    cleanup()
