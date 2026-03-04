# Hiseeu HD118-PZ — Technische Dokumentation

> Alle Erkenntnisse aus Reverse-Engineering, Debug-Sessions und Protokoll-Analyse.
> Stand: März 2026

---

## 1. Kamera-Hardware

| Eigenschaft       | Wert                                    |
|-------------------|-----------------------------------------|
| Modell            | Hiseeu HD118-PZ                         |
| Chipsatz          | **Novatek NT98566**                     |
| Firmware-Basis    | **XM / Xiongmai** (nicht Hiseeu-eigen!) |
| Max. Auflösung    | 3840×2160 (4K / 8 MP)                  |
| PTZ               | Ja (Pan/Tilt mechanisch, Zoom optisch)  |
| AI-Features       | Human Detection, Auto-Tracking, Smart Detect |
| App-Steuerung     | iCSee / XMEye                           |
| PoE               | Ja                                      |

### Wichtige Erkenntnis: Xiongmai-Firmware
Die Kamera wird als "Hiseeu" verkauft, läuft aber intern auf **Xiongmai (XM) Firmware**.
Das bedeutet:
- Sie spricht das **XM Binary Protocol (DVRIP)** auf Port 34567
- ONVIF ist auf einem **nicht-Standard-Port** (8899 statt 80/8080)
- Die RTSP-URLs folgen dem XM-Schema, nicht dem ONVIF-Standard
- Die AI-Tracking-Features sind XM-spezifisch und nur über DVRIP steuerbar

---

## 2. Netzwerk-Endpunkte

| Dienst            | Port  | Protokoll       | Auth                    |
|-------------------|-------|-----------------|-------------------------|
| **RTSP**          | 554   | RTSP/TCP        | URL-embedded (s. unten) |
| **ONVIF**         | 8899  | HTTP/SOAP       | Keine Auth nötig!       |
| **XM/DVRIP**      | 34567 | TCP/Binary+JSON | MD5-Hash (DVRIP-Web)    |
| iCSee/XMEye Cloud | diverse | UDP/TCP       | Cloud-basiert           |

### IP-Adresse (DHCP/statisch)
```
192.168.178.122
```

---

## 3. RTSP-Streams

### Von ONVIF erkannte Stream-URIs

Die Kamera liefert über ONVIF (`GetStreamUri`) drei Profile:

| Profil       | Auflösung   | Codec   | RTSP-URL |
|--------------|-------------|---------|----------|
| **mainStream** | 3840×2160 | H.264   | `rtsp://192.168.178.122:554/user=admin_password=tlJwpbo6_channel=0_stream=0&onvif=0.sdp?real_stream` |
| **subStream**  | 640×360   | H.264   | `rtsp://192.168.178.122:554/user=admin_password=tlJwpbo6_channel=0_stream=1&onvif=0.sdp?real_stream` |
| **snapStream** | 704×576   | JPEG    | `rtsp://192.168.178.122:554/user=admin_password=tlJwpbo6_channel=0_stream=2&onvif=0.sdp?real_stream` |

### RTSP-URL-Format (XM-spezifisch!)
```
rtsp://<IP>:554/user=<USER>_password=<HASHED_PW>_channel=<CH>_stream=<N>&onvif=0.sdp?real_stream
```

- `stream=0` → Main (4K)
- `stream=1` → Sub (640×360)
- `stream=2` → Snap (JPEG)
- Das **Passwort in der URL ist NICHT das Klartext-Passwort**, sondern ein spezieller Hash (`tlJwpbo6` für leeres Passwort)
- `channel=0` → Erste (einzige) Kamera
- `&onvif=0` und `?real_stream` sind pflicht

### Legacy/Standard-URLs (funktionieren NICHT zuverlässig)
Diese URLs werden oft in Anleitungen genannt, funktionieren bei dieser Kamera aber **nicht** oder liefern den falschen Stream:
```
rtsp://admin:@192.168.178.122:554/stream     ← NICHT verwenden
rtsp://admin:@192.168.178.122:554/stream2    ← NICHT verwenden
rtsp://192.168.178.122:554/11                ← NICHT verwenden
rtsp://192.168.178.122:554/12                ← NICHT verwenden
```

### Wichtig: Stream-Auswahl
- **Für Live-Vorschau auf Pi:** Sub-Stream (640×360 H264) verwenden!
  - 4K Main-Stream verursacht Vulkan OOM, DRM-Prime-Fehler, GPU-Überlastung
  - 640×360 H264 wird problemlos per Software dekodiert (<10% GPU)
- **Für Aufnahme:** Main-Stream (4K) per `ffmpeg -c:v copy` (kein Re-Encoding)

---

## 4. ONVIF-Schnittstelle

### Verbindung
```python
from onvif import ONVIFCamera
cam = ONVIFCamera('192.168.178.122', 8899, 'admin', '')
```

- **Port 8899** (nicht der ONVIF-Standard 80 oder 8080!)
- **Keine Authentifizierung** nötig (Username `admin`, Passwort leer)
- Python-Bibliothek: `python-onvif-zeep`

### Verfügbare Dienste
- **Media Service** (`create_media_service()`)
  - `GetProfiles()` → 3 Profile (mainStream, subStream, snapStream)
  - `GetStreamUri()` → RTSP-URLs pro Profil
- **PTZ Service** (`create_ptz_service()`)
  - `ContinuousMove()` → Pan/Tilt/Zoom mit Geschwindigkeit
  - `Stop()` → Bewegung stoppen

### PTZ-Steuerung (ContinuousMove)
```python
move_req = ptz_service.create_type('ContinuousMove')
move_req.ProfileToken = profile.token
move_req.Velocity = {
    'PanTilt': {'x': float(pan), 'y': float(tilt)},   # -1.0 bis +1.0
    'Zoom':    {'x': float(zoom_speed)}                 # -1.0 bis +1.0
}
ptz_service.ContinuousMove(move_req)
```

### PTZ-Stop
```python
ptz_service.Stop({'ProfileToken': profile.token})
```

### Performance der ONVIF-Calls
- Jeder ContinuousMove/Stop ist ein **synchroner HTTP/SOAP Request**
- Typische Latenz: **26-200ms pro Call** (Netzwerk + Kamera-Processing)
- Bei hoher Last oder schlechtem WLAN: bis zu 500ms+
- **Kritisch:** Muss in Non-Blocking-Thread ausgelagert werden, sonst blockiert der Control-Loop

### Auto-Reconnect
- Nach 3 aufeinanderfolgenden ONVIF-Fehlern: vollständiger Reconnect
- Neue `ONVIFCamera`-Instanz, neue Services, neue Request-Objekte

---

## 5. XM Binary Protocol (DVRIP) — Port 34567

### Überblick
Das proprietäre Xiongmai-Protokoll ermöglicht Zugriff auf Funktionen, die über ONVIF **nicht erreichbar** sind — insbesondere die AI-Tracking-Konfiguration.

### Paket-Format
```
Offset  Länge  Beschreibung
0       4      Magic: FF 00 00 00
4       4      Session-ID (Little-Endian uint32)
8       4      Sequence (unused, 0)
12      2      Reserved (0, 0)
14      2      Message-ID (Little-Endian uint16)
16      4      Daten-Länge (Little-Endian uint32)
20      N      JSON-Payload + 0x0A (Newline als Terminator)
```

### Verbindung & Login
```python
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(('192.168.178.122', 34567))

# Login (Message-ID 1000)
login_data = {
    "EncryptType": "MD5",
    "LoginType": "DVRIP-Web",
    "PassWord": "<MD5-Hash>",
    "UserName": "admin"
}
```

### Passwort-Hashing (XM-spezifisch!)
```python
def hash_password(password):
    m = hashlib.md5(password.encode('utf-8') if password else b"").digest()
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    return "".join(chars[(m[2*i] + m[2*i+1]) % len(chars)] for i in range(8))
```
- Leeres Passwort → Hash: `tlJwpbo6`
- Das ist **kein Standard-MD5**, sondern ein XM-proprietärer Hash

### Login-Antwort
```json
{
    "Ret": 100,
    "SessionID": "0x00000001",
    "AliveInterval": 20,
    "ChannelNum": 1,
    "DeviceType": "IPC"
}
```
- `Ret: 100` = Erfolg
- `Ret: 0` = Erfolg (bei Config-Operationen)
- Andere Werte = Fehler

### Message-IDs
| ID   | Funktion          |
|------|-------------------|
| 1000 | Login             |
| 1040 | SetConfig         |
| 1042 | GetConfig         |
| 1400 | OPPTZControl      |

### Config lesen (GetConfig, ID 1042)
```json
{
    "Name": "Detect.HumanDetection",
    "SessionID": "0x00000001"
}
```

### Config schreiben (SetConfig, ID 1040)
```json
{
    "Name": "Detect.HumanDetection",
    "Detect.HumanDetection": {"Enable": false},
    "SessionID": "0x00000001"
}
```

### PTZ-Steuerung über DVRIP (ID 1400)
```json
{
    "Name": "OPPTZControl",
    "OPPTZControl": {
        "Command": "AutoScanStop",
        "Parameter": {
            "AUX": {"Number": 0, "Status": "On"},
            "Channel": 0,
            "MenuOpts": "Enter",
            "POINT": {"bottom": 0, "left": 0, "right": 0, "top": 0},
            "Pattern": "SetBegin",
            "Preset": 0,
            "Step": 0,
            "Tour": 0
        }
    },
    "SessionID": "0x00000001"
}
```

---

## 6. AI-Tracking — Das Hauptproblem

### Was passiert
Die Kamera hat eingebautes AI-Tracking (Personenerkennung + Auto-Verfolgung).
Wenn aktiv, **übernimmt die Kamera die PTZ-Steuerung eigenmächtig** und verfolgt erkannte Personen. Das macht manuelle PTZ-Steuerung unmöglich.

### Betroffene Config-Keys
Durch systematisches Testen (28 von 28 Configs erfolgreich gesetzt) wurden folgende relevante Konfigurationen identifiziert:

#### Haupt-Verursacher (AI-Detection)
| Config-Name                | Funktion                    |
|----------------------------|-----------------------------|
| `Detect.HumanDetection`   | **Haupt-Trigger** — Personenerkennung |
| `Detect.SmartDetect`      | Smart-Erkennung allgemein   |
| `Detect.HumanoidDetect`   | Humanoide Erkennung         |

#### Alarm-System (löst Aktionen aus)
| Config-Name                | Funktion                    |
|----------------------------|-----------------------------|
| `Alarm.SmartAlarm`         | Smart-Alarm (mit Sub-Keys: `HumanoidEnable`, `SmdEnable`, `AiEnable`) |
| `Alarm.HumanAlarm`        | Personen-Alarm              |
| `Alarm.HumanDetection`    | Personen-Erkennungs-Alarm   |

#### PTZ Auto-Tracking (bewegt die Kamera)
| Config-Name                | Funktion                    |
|----------------------------|-----------------------------|
| `Camera.PtzAutoTrack`      | PTZ Auto-Track (CamelCase)  |
| `Camera.PTZAutoTrack`      | PTZ Auto-Track (ALLCAPS)    |
| `PTZAutoTrack`             | PTZ Auto-Track (root)       |
| `Ptz.AutoTracking`         | PTZ Auto-Tracking           |
| `Ptz.AutoTrack`            | PTZ Auto-Track              |
| `Camera.PtzTrack`          | PTZ Track                   |
| `PTZTrack`                 | PTZ Track (mit `AutoTrack`-Sub-Key) |

#### Intelligente Verfolgung
| Config-Name                | Funktion                    |
|----------------------------|-----------------------------|
| `fVideo.IntelliTrace`      | Intelligente Verfolgung     |
| `fVideo.IntelliTrack`      | Intelligentes Tracking      |
| `IntelliTrace`             | IntelliTrace (root)         |
| `fVideo.SmartDetect`       | Smart-Erkennung (Video)     |

#### Netzwerk & Tour
| Config-Name                | Funktion                    |
|----------------------------|-----------------------------|
| `NetWork.NetSmartDetect`   | Netzwerk-Smart-Erkennung    |
| `Camera.GuardTour`         | Guard-Tour (automatische Rundfahrt) |

#### PTZ-Stop-Befehle (Message-ID 1400)
| Befehl             | Funktion                       |
|--------------------|--------------------------------|
| `AutoScanStop`     | Stoppt automatisches Scannen   |
| `TourStop`         | Stoppt Guard-Tour              |

### Deaktivierungs-Strategie
1. **Alle** oben genannten Configs auf `{"Enable": false}` setzen
2. PTZ-Stop-Befehle senden (`AutoScanStop`, `TourStop`)
3. Nach 0.5s Wartezeit: **Verifizieren** dass `CHECK_CONFIGS` wirklich aus sind
4. **Watchdog**: Alle 30 Sekunden erneut prüfen (Kamera kann Features selbständig reaktivieren!)

### Ergebnis
- 28/28 Config-Writes erfolgreich (Ret: 100 oder 0)
- AI-Tracking nach Deaktivierung **zuverlässig aus**
- Watchdog fängt eventuelle Reaktivierungen ab

---

## 7. Video-Stream — Probleme & Lösungen

### Chronologie der Stream-Probleme

#### Problem 1: Blaues Bild
- **Ursache:** `probesize=32` und `analyzeduration=0` zu klein → ffmpeg/mpv konnte H264-Stream nicht korrekt parsen
- **Fix:** `probesize=65536`, `analyzeduration=500000`

#### Problem 2: DRM Prime Mapping Failed
- **mpv-Log:** `drm_prime mapping DRM dmabuf failed`
- **Ursache:** mpv versuchte Hardware-Decode via DRM prime auf dem Pi → Treiber unterstützt 4K nicht
- **Zusatz-Problem:** Stream war versehentlich der **Main-Stream (3840×2160)** statt Sub-Stream
- **Fix:** `--hwdec=auto-copy`, korrekte Sub-Stream-URL

#### Problem 3: Frozen Image + Erratische PTZ
- **Ursache:** `--untimed` in mpv → zerstört RTSP-Timing, Bild friert ein
- **Fix:** `--untimed` entfernt, `--cache=no` hinzugefügt

#### Problem 4: Vulkan Out-of-Memory
- **mpv-Log:** `VK_ERROR_OUT_OF_HOST_MEMORY`
- **Ursache:** Pi hat nicht genug GPU-RAM für 4K-Texturen in Vulkan
- **Fix:** `--gpu-api=opengl` (Vulkan deaktiviert)

#### Problem 5: Falsche Sub-Stream URLs
- **Ursache:** Standard-URLs (`/stream2`, `/12` etc.) existieren nicht auf dieser Kamera
- **Fix:** ONVIF-Discovery → echte URL aus `GetStreamUri` verwenden

#### Finale Lösung
```
mpv --fullscreen --no-audio --profile=low-latency --cache=no --cache-pause=no \
    --demuxer-lavf-o=fflags=+nobuffer+fastseek+discardcorrupt,rtsp_transport=tcp,analyzeduration=500000,probesize=65536 \
    --demuxer-readahead-secs=0.5 --interpolation=no --video-latency-hacks=yes \
    --vd-lavc-threads=4 --hwdec=no --gpu-api=opengl --force-seekable=no \
    --framedrop=decoder+vo \
    "rtsp://192.168.178.122:554/user=admin_password=tlJwpbo6_channel=0_stream=1&onvif=0.sdp?real_stream"
```
- Sub-Stream 640×360 H264 → Software-Decode → **funktioniert zuverlässig**
- **<10% GPU-Auslastung** auf dem Raspberry Pi
- Bild aktualisiert sich flüssig, hängt nicht

---

## 8. PTZ-Steuerung — Probleme & Lösungen

### Problem: "EXTREM willkürliche" Steuerung
Die Kamera reagierte erratisch auf Joystick-Eingaben, keine sinnvolle Echtzeitsteuerung möglich.

### Ursachen (diagnostiziert)

1. **ONVIF-Calls blockieren den Control-Loop**
   - Jeder `ContinuousMove()` / `Stop()` ist ein synchroner HTTP-Request (26-200ms)
   - Bei 50ms Loop-Intervall (20 Hz) blockiert ein einziger Call den halben Zyklus
   - Joystick-Eingaben gehen verloren, Befehle kommen verspätet

2. **ADC-Rauschen vom MCP3008**
   - MCP3008 über SPI liefert verrauschte Werte (±2-5 LSB Jitter)
   - Ohne Glättung: Werte pendeln ständig über Deadzone-Grenze
   - Ergebnis: Move-Stop-Move-Stop-Chaos

3. **Deadzone ohne Hysterese**
   - Wert am Deadzone-Rand toggelt bei jedem Abtastzyklus
   - Kamera bekommt widersprüchliche Befehle

### Lösung

1. **Non-Blocking PTZ-Worker-Thread**
   - ONVIF-Befehle werden in Background-Thread ausgelagert
   - Control-Loop queut nur den **jeweils letzten** Befehl (Fire-and-Forget)
   - Ältere Befehle werden automatisch verworfen
   - Loop wird nie mehr durch Netzwerk-Latenz blockiert

2. **Exponential Moving Average (EMA)**
   - Alpha = 0.4 (Mischung: 40% neuer Wert, 60% alter Wert)
   - Glättet ADC-Rauschen, erhält aber Reaktionsfähigkeit
   - Angewendet auf X, Y und Zoom-Poti

3. **Deadzone mit Hysterese**
   - Hysterese: 0.03 (zusätzlich zur Deadzone)
   - Bewegung startet erst bei `DEADZONE + 0.03` (0.11)
   - Bewegung stoppt erst bei `DEADZONE` (0.08)
   - Verhindert Jitter-Toggeln am Rand

---

## 9. Raspberry Pi — Hardware-Besonderheiten

### Plattform
| Eigenschaft    | Wert                      |
|----------------|---------------------------|
| Architektur    | aarch64 (ARM 64-bit)      |
| OS             | Debian (Raspberry Pi OS)  |
| Kernel         | 6.12.47                   |

### GPU-Einschränkungen (ermittelt durch Debug)
| Feature           | Status        | Details |
|-------------------|---------------|---------|
| CUDA              | ❌ Nicht verfügbar | Nur NVIDIA |
| VDPAU             | ❌ Nicht verfügbar | Nur NVIDIA |
| Vulkan            | ⚠️ Defekt bei 4K | `VK_ERROR_OUT_OF_HOST_MEMORY` bei 3840×2160 |
| DRM Prime         | ⚠️ Defekt       | `drm_prime mapping DRM dmabuf failed` |
| OpenGL            | ✅ Funktioniert  | Standard-Fallback |
| V4L2 (HW-Decode)  | ⚠️ Nicht für H264/4K | Pi-HW-Decoder begrenzt |

### Empfehlung
- **Immer `--hwdec=no --gpu-api=opengl`** für mpv auf dem Pi
- Sub-Stream (640×360) ist für Software-Decode ideal (<10% GPU)
- 4K Main-Stream nur für Aufnahme (`ffmpeg -c:v copy`, kein Decode!)

### Hardware-Anbindung (MCP3008 ADC)
```
MCP3008 über SPI:
  Channel 0 → Zoom-Poti (0.0 - 1.0)
  Channel 2 → Joystick Y (0.0 - 1.0, Mitte ≈ 0.5)
  Channel 3 → Joystick X (0.0 - 1.0, Mitte ≈ 0.5)

GPIO:
  Pin 17   → Joystick-Button (Pull-Up, active low)
```

---

## 10. Aufnahme

### Methode
- **ffmpeg Stream-Copy** vom Main-Stream (4K, kein Re-Encoding)
- Crash-sichere MP4: `movflags=frag_keyframe+empty_moov` (fragmentiertes MP4)
- Bei Absturz/Stromausfall: Datei bis zum letzten Keyframe lesbar

### Kommando
```bash
ffmpeg -rtsp_transport tcp \
    -i "rtsp://192.168.178.122:554/user=admin_password=tlJwpbo6_channel=0_stream=0&onvif=0.sdp?real_stream" \
    -c:v copy -c:a aac \
    -movflags frag_keyframe+empty_moov \
    -y ~/Aufnahmen/aufnahme_YYYYMMDD_HHMMSS.mp4
```

### Hinweis zu +faststart
`+faststart` wurde bewusst **nicht** verwendet:
- Erfordert Seek zurück zum Dateianfang nach Abschluss
- Bei Absturz: Datei unlesbar (moov-Atom fehlt)
- `frag_keyframe+empty_moov` ist die sichere Alternative

---

## 11. Bekannte Eigenheiten & Fallstricke

### Kamera-seitig
1. **AI reaktiviert sich selbst** — Die Kamera kann AI-Tracking eigenständig wieder einschalten (z.B. nach Firmware-Update, Neustart, oder zeitgesteuert). Deshalb: **Watchdog alle 30s!**
2. **ONVIF-Port nicht Standard** — Port 8899, nicht 80/8080. Viele ONVIF-Tools finden die Kamera nicht automatisch.
3. **Passwort in RTSP-URL ist ein Hash** — Nicht das Klartext-Passwort! Der Hash `tlJwpbo6` entspricht einem leeren Passwort.
4. **Config-Keys sind Case-Sensitiv und inkonsistent** — `PtzAutoTrack` vs. `PTZAutoTrack` vs. `AutoTracking` — alle drei existieren als separate Configs.
5. **Dual-Protocol-Zwang** — ONVIF für PTZ+Streams, aber XM/DVRIP für AI-Config. Kein einzelnes Protokoll deckt alles ab.

### Raspberry Pi-seitig
1. **Kein Hardware-Decode für 4K** — Weder V4L2 noch DRM prime funktionieren zuverlässig für 3840×2160 H264
2. **Vulkan crasht bei großen Texturen** — `VK_ERROR_OUT_OF_HOST_MEMORY`
3. **`--untimed` zerstört RTSP** — mpv Option die bei lokalen Dateien Sinn macht, aber RTSP-Streams einfriert
4. **`--video-sync=audio` + `--no-audio`** → mpv-Fehler (sich widersprechende Optionen)
5. **`--demuxer-lavf-o` nur EINMAL** — Bei doppelter Angabe ignoriert mpv die zweite, keine Warnung

### Steuerungs-seitig
1. **MCP3008 ADC rauscht** — ±2-5 LSB Jitter, EMA-Glättung zwingend nötig
2. **ONVIF ist langsam** — HTTP/SOAP Round-Trip 26-200ms, blockiert den Control-Loop wenn synchron aufgerufen
3. **ContinuousMove braucht expliziten Stop** — Kamera bewegt sich endlos bis `Stop()` kommt. Stop muss 3× wiederholt werden (Paketverlust).

---

## 12. Diagnose-Tools

### probe_streams.py
Testet 20 verschiedene RTSP-URLs per ffprobe und zeigt welche funktionieren:
```bash
python3 probe_streams.py
```

### device_debug.py
Debug-Tool für Kamera-Erkennung und Protokoll-Tests.

### Nützliche Debug-Befehle
```bash
# ONVIF-Profile und Streams anzeigen (in Python)
from onvif import ONVIFCamera
cam = ONVIFCamera('192.168.178.122', 8899, 'admin', '')
media = cam.create_media_service()
for p in media.GetProfiles():
    print(p.Name, p.VideoEncoderConfiguration.Resolution)

# RTSP-Stream testen
ffprobe -rtsp_transport tcp \
    "rtsp://192.168.178.122:554/user=admin_password=tlJwpbo6_channel=0_stream=1&onvif=0.sdp?real_stream"

# XM-Verbindung testen
python3 -c "from src import xm_protocol as xm; s,i = xm.connect_and_login(); print('Session:', hex(i)); s.close()"

# mpv mit Debug-Output
mpv --msg-level=all=v --hwdec=no --gpu-api=opengl \
    "rtsp://192.168.178.122:554/user=admin_password=tlJwpbo6_channel=0_stream=1&onvif=0.sdp?real_stream"
```

---

## 13. Projektstruktur

```
PTZ_Control/
├── main.py                 # Einstiegspunkt: Threads starten, Cleanup
├── config/
│   └── config.py           # Alle Konstanten (IP, Ports, Schwellwerte)
├── src/
│   ├── state.py            # Geteilte Globals (recording, running, ...)
│   ├── hardware.py         # MCP3008 ADC + Button (gpiozero)
│   ├── xm_protocol.py      # XM Binary Protocol (Port 34567)
│   ├── ai_tracking.py      # AI-Erkennung, Deaktivierung, Watchdog
│   ├── onvif_ptz.py        # ONVIF PTZ + Stream-URI-Discovery
│   ├── controls.py         # Steuerungs-Loop (Joystick → PTZ)
│   ├── stream.py           # Live-Vorschau (mpv)
│   ├── recording.py        # Aufnahme + Screenshot (ffmpeg)
│   └── overlay.py          # Tkinter-Overlay (Aufnahme/AI-Warnung)
├── probe_streams.py        # Diagnose: RTSP-URL-Tester
├── device_debug.py         # Diagnose: Kamera-Debug
└── requirements.txt        # Python-Abhängigkeiten
```

---

## 14. Abhängigkeiten

```
python-onvif-zeep    # ONVIF-Client
gpiozero             # GPIO/SPI (MCP3008, Button)
spidev               # SPI-Treiber für MCP3008
```

System-Pakete:
```
mpv                  # Live-Vorschau
ffmpeg / ffprobe     # Aufnahme, Screenshot, Stream-Diagnose
```

---

## 15. Deployment

```bash
# Auf den Pi kopieren:
scp -r PTZ_Control/* kaderblick@192.168.178.10:/home/kaderblick/camera_control/

# Auf dem Pi starten:
cd /home/kaderblick/camera_control
python3 main.py
```
