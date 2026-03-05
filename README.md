# PTZ Control — Fußball-Kamerasteuerung

Manuelle PTZ-Steuerung einer **Hiseeu HD118-PZ** Kamera über Joystick, Poti und Button auf einem **Raspberry Pi**. Entwickelt für die Aufnahme von Fußballspielen aus erhöhter Position (z. B. Flutlichtmast).

## Features

- **Pan/Tilt** — Joystick steuert Schwenk und Neigung (proportional, quadratische Kurve)
- **Zoom** — Poti steuert Zoom-Geschwindigkeit mit breiter Deadzone
- **Live-Vorschau** — Sub-Stream (640×360) über mpv im Vollbild, minimale Latenz (~200 ms)
- **Aufnahme** — Main-Stream in voller Qualität via ffmpeg Stream-Copy (kein Re-Encoding)
- **Screenshot** — Einzelbild aus dem Main-Stream
- **AI-Tracking-Schutz** — Automatische Deaktivierung aller KI-Features + Watchdog
- **Bildschirm-Overlay** — Aufnahme-Indikator und AI-Warnung als transparentes Fenster

## Hardware

### Kamera

| Eigenschaft    | Wert                                    |
|----------------|-----------------------------------------|
| Modell         | Hiseeu HD118-PZ                         |
| Chip           | Novatek NT98566                         |
| Firmware       | Xiongmai (XM), V5.00.R02               |
| ONVIF-Port     | 8899                                    |
| RTSP-Port      | 554                                     |
| DVRIP-Port     | 34567 (XM Binary Protocol)              |

### Raspberry Pi

| Komponente     | Anschluss                               |
|----------------|-----------------------------------------|
| **Joystick X** | MCP3008 ADC, Kanal 3 (SPI)             |
| **Joystick Y** | MCP3008 ADC, Kanal 2 (SPI)             |
| **Zoom-Poti**  | MCP3008 ADC, Kanal 0 (SPI)             |
| **Button**     | GPIO 17 (Pull-Up)                       |

### Verkabelung MCP3008

```
MCP3008     Raspberry Pi
────────    ────────────
VDD    ───  3.3V
VREF   ───  3.3V
AGND   ───  GND
DGND   ───  GND
CLK    ───  SCLK (GPIO 11)
DOUT   ───  MISO (GPIO 9)
DIN    ───  MOSI (GPIO 10)
CS     ───  CE0  (GPIO 8)
```

## Bedienung

| Eingabe              | Aktion                          |
|----------------------|---------------------------------|
| Joystick bewegen     | Pan/Tilt (proportional)         |
| Poti nach rechts     | Rein-Zoomen                     |
| Poti nach links      | Raus-Zoomen                     |
| Button kurz drücken  | Screenshot                      |
| Button 3 Sek. halten | Aufnahme starten / stoppen      |

Aufnahmen und Screenshots werden in `~/Aufnahmen/` gespeichert.

## Installation

### Voraussetzungen

- Raspberry Pi mit Raspberry Pi OS
- Python 3.9+
- SPI aktiviert (`sudo raspi-config` → Interface Options → SPI)
- mpv und ffmpeg installiert:
  ```bash
  sudo apt install mpv ffmpeg
  ```

### Setup

```bash
git clone https://github.com/mastercad/Kaderblick-PTZ_Control.git
cd Kaderblick-PTZ_Control
pip install -r requirements.txt
```

### Konfiguration

Alle Einstellungen in **einer** Datei: `config/config.py`

```python
CAMERA_IP   = '192.168.178.122'   # IP der Kamera
CAMERA_PORT = 8899                # ONVIF-Port
USERNAME    = 'admin'
PASSWORD    = ''

PAN_MAX  = 1.0       # Maximale Pan-Geschwindigkeit
TILT_MAX = 1.0       # Maximale Tilt-Geschwindigkeit
ZOOM_MAX = 1.0       # Maximale Zoom-Geschwindigkeit
DEADZONE = 0.12      # Joystick-Deadzone
ZOOM_DEADZONE = 0.30 # Zoom-Poti-Deadzone
```

## Starten

```bash
python3 main.py
```

Beim Start passiert automatisch:
1. ONVIF-Verbindung zur Kamera herstellen
2. AI-Tracking deaktivieren (28 Features)
3. Joystick/Poti kalibrieren (**nicht berühren!**)
4. Live-Vorschau öffnen (Vollbild)
5. Steuerungs-Loop und AI-Watchdog starten

Beenden: Vorschau-Fenster schließen oder `Ctrl+C`.

## Projektstruktur

```
PTZ_Control/
├── main.py                 # Einstiegspunkt — startet alles
├── config/
│   └── config.py           # Alle Einstellungen (IP, Ports, Schwellwerte)
├── src/
│   ├── controls.py         # Steuerungs-Loop (Joystick/Poti → PTZ)
│   ├── onvif_ptz.py        # ONVIF PTZ-Steuerung + Auto-Reconnect
│   ├── stream.py           # Live-Vorschau (mpv, RTSP, Low-Latency)
│   ├── recording.py        # Aufnahme (ffmpeg Stream-Copy) + Screenshot
│   ├── ai_tracking.py      # AI-Deaktivierung + Watchdog
│   ├── xm_protocol.py      # XM Binary Protocol (DVRIP, Port 34567)
│   ├── hardware.py          # GPIO/ADC Setup (MCP3008, Button)
│   ├── overlay.py          # Bildschirm-Overlay (Aufnahme/AI-Warnung)
│   └── state.py            # Geteilter Zustand (globale Flags)
├── diagnose/               # Diagnose- und Test-Scripts
│   ├── device_debug.py     # Kamera-Info auslesen
│   ├── diagnose_joystick.py# Joystick/Poti-Werte live anzeigen
│   ├── diagnose_ptz.py     # PTZ-Funktionen einzeln testen
│   ├── diagnose_latenz.py  # Stream-Latenz messen
│   ├── probe_streams.py    # RTSP-Streams erkennen
│   ├── test_ptz_minimal.py # Minimaler PTZ-Test
│   ├── test_absolute_zoom.py # ONVIF Zoom-Modi testen
│   ├── test_xm_protocol.py# XM-Protokoll testen
│   ├── disable_ai_tracking.py # AI einzeln deaktivieren
│   ├── configure_stream.py # Stream-Einstellungen via ONVIF
│   └── configure_stream_xm.py # Stream-Einstellungen via DVRIP
├── requirements.txt
└── KAMERA_DOKUMENTATION.md # Technische Doku zur Kamera
```

## Architektur

Das Programm startet drei Threads:

| Thread       | Modul           | Aufgabe                                      |
|--------------|-----------------|----------------------------------------------|
| **Stream**   | `stream.py`     | mpv-Prozess für Live-Vorschau (Sub-Stream)   |
| **Control**  | `controls.py`   | 20-Hz-Loop: Hardware lesen → ONVIF-Befehle   |
| **Watchdog** | `ai_tracking.py`| Prüft alle 30s ob AI-Tracking wieder aktiv ist|

### Steuerungs-Flow

```
Joystick/Poti (analog)
       │
       ▼
   MCP3008 ADC (SPI)
       │
       ▼
  Auto-Kalibrierung
  (Nullposition = Ruhezustand beim Start)
       │
       ▼
  Deadzone + Quadratische Kurve
  (feinfühlig bei kleiner Auslenkung)
       │
       ▼
  ONVIF ContinuousMove
  (Pan + Tilt + Zoom in einem Befehl)
       │
       ▼
  Kamera bewegt sich
```

## Bekannte Eigenheiten der Kamera

- **ONVIF AbsoluteMove** wird akzeptiert (HTTP 200), aber **nicht ausgeführt** — typisch für Xiongmai-Firmware
- **ONVIF SetVideoEncoderConfiguration** ebenfalls fake — Stream-Einstellungen nur über DVRIP änderbar
- **Speed-Werte bei ContinuousMove** werden von der Kamera nicht proportional umgesetzt — Bewegung ist immer gleich schnell
- **Port 80** ist ein Webserver (kein ONVIF!) — gibt HTML-404 als HTTP 200 zurück
- **AI-Tracking** aktiviert sich nach Kamera-Neustart selbst wieder → daher der Watchdog

## Diagnose

Die Scripts in `diagnose/` helfen bei Problemen:

```bash
# Joystick-/Poti-Werte live anzeigen
python3 diagnose/diagnose_joystick.py

# PTZ-Funktionen testen
python3 diagnose/diagnose_ptz.py

# Stream-Latenz messen
python3 diagnose/diagnose_latenz.py

# Kamera-Info auslesen
python3 diagnose/device_debug.py

# ONVIF Zoom-Modi testen (AbsoluteMove, RelativeMove, ContinuousMove)
python3 diagnose/test_absolute_zoom.py
```

## Lizenz

Privates Projekt für den Fußballverein.
