#!/usr/bin/env python3
"""
Joystick/Poti Diagnose — zeigt Rohwerte in Echtzeit.

Starten: python3 diagnose_joystick.py
Beenden: Ctrl+C

Zeigt:
  - Rohwerte von MCP3008 (0.0 - 1.0)
  - Berechnete Pan/Tilt (-1.0 bis +1.0)
  - Ob Hardware- oder Software-SPI aktiv ist
  - Ob der Wert in der Deadzone liegt
"""

import time
import sys

try:
    from gpiozero import MCP3008
except ImportError:
    print("FEHLER: gpiozero nicht installiert!")
    print("  pip install gpiozero")
    sys.exit(1)

DEADZONE = 0.08

# SPI-Typ erkennen
spi_type = "UNBEKANNT"
try:
    import spidev
    s = spidev.SpiDev()
    s.open(0, 0)
    s.close()
    spi_type = "HARDWARE-SPI ✓"
except Exception as e:
    spi_type = f"SOFTWARE-FALLBACK ✗ ({e})"

print(f"SPI-Status: {spi_type}")
print()

# MCP3008 initialisieren
try:
    joy_x = MCP3008(channel=3)
    joy_y = MCP3008(channel=2)
    pot   = MCP3008(channel=0)
except Exception as e:
    print(f"FEHLER bei MCP3008-Init: {e}")
    sys.exit(1)

print("Joystick-Diagnose läuft... (Ctrl+C zum Beenden)")
print("=" * 70)
print(f"{'raw_x':>8} {'raw_y':>8} {'raw_z':>8} | {'pan':>7} {'tilt':>7} | {'dz_x':>5} {'dz_y':>5} | Jitter")
print("-" * 70)

# Jitter-Tracking
samples_x = []
samples_y = []
samples_z = []
JITTER_WINDOW = 20

try:
    while True:
        rx = joy_x.value
        ry = joy_y.value
        rz = pot.value

        pan  = rx * 2.0 - 1.0
        tilt = ry * 2.0 - 1.0

        in_dz_x = "DZ" if abs(pan) < DEADZONE else "  "
        in_dz_y = "DZ" if abs(tilt) < DEADZONE else "  "

        # Jitter berechnen (Standardabweichung der letzten N Samples)
        samples_x.append(rx)
        samples_y.append(ry)
        samples_z.append(rz)
        if len(samples_x) > JITTER_WINDOW:
            samples_x.pop(0)
            samples_y.pop(0)
            samples_z.pop(0)

        if len(samples_x) >= 5:
            mean_x = sum(samples_x) / len(samples_x)
            mean_y = sum(samples_y) / len(samples_y)
            jit_x = max(samples_x) - min(samples_x)
            jit_y = max(samples_y) - min(samples_y)
            jitter_info = f"x±{jit_x:.4f}  y±{jit_y:.4f}"
        else:
            jitter_info = "Sammle..."

        print(f"\r{rx:8.4f} {ry:8.4f} {rz:8.4f} | {pan:+7.4f} {tilt:+7.4f} | {in_dz_x:>5} {in_dz_y:>5} | {jitter_info}", end="", flush=True)

        time.sleep(0.05)  # 20 Hz wie der echte Loop

except KeyboardInterrupt:
    print("\n\nZusammenfassung:")
    if samples_x:
        print(f"  X-Jitter (letzte {len(samples_x)} Samples): {max(samples_x)-min(samples_x):.4f}")
        print(f"  Y-Jitter (letzte {len(samples_y)} Samples): {max(samples_y)-min(samples_y):.4f}")
        print(f"  Z-Jitter (letzte {len(samples_z)} Samples): {max(samples_z)-min(samples_z):.4f}")
        print(f"  X-Mitte (Ruhe): ~{sum(samples_x)/len(samples_x):.4f} (ideal: 0.5000)")
        print(f"  Y-Mitte (Ruhe): ~{sum(samples_y)/len(samples_y):.4f} (ideal: 0.5000)")
    print()
    if spi_type.startswith("SOFTWARE"):
        print("  ⚠ SOFTWARE-SPI aktiv! Das verursacht Jitter.")
        print("    → sudo raspi-config → Interface → SPI → Enable → Reboot")
