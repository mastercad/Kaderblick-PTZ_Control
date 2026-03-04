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

| Profil       | Auflösung   | ONVIF sagt | **Tatsächlich** | FPS | Bitrate | RTSP-URL |
|--------------|-------------|------------|-----------------|-----|---------|----------|
| **mainStream** | 3840×2160 | H.264     | **H.265 (HEVC)** | 17  | 6305 kbps | `rtsp://...stream=0...` |
| **subStream**  | 640×360   | H.264     | **H.265 (HEVC)** | 25* | 106 kbps  | `rtsp://...stream=1...` |
| **snapStream** | 704×576   | JPEG      | H.264           | 1   | 512 kbps  | `rtsp://...stream=2...` |

> **⚠️ KRITISCH: ONVIF lügt über den Codec!** Beide Video-Streams sind **H.265 (HEVC)**, nicht H.264.
> Dies wurde per ffprobe verifiziert und durch die DVRIP-Config (`Simplify.Encode`) bestätigt.
> ONVIF `GetVideoEncoderConfiguration` meldet fälschlicherweise `H264` für alle Profile.
>
> *Sub-Stream FPS: Ab Werk **5 FPS** — per DVRIP auf **25 FPS** geändert (siehe Abschnitt 5.2).
> Diese Einstellung geht möglicherweise bei Kamera-Neustart verloren!

Vollständige RTSP-URLs:
```
Main: rtsp://192.168.178.122:554/user=admin_password=tlJwpbo6_channel=0_stream=0&onvif=0.sdp?real_stream
Sub:  rtsp://192.168.178.122:554/user=admin_password=tlJwpbo6_channel=0_stream=1&onvif=0.sdp?real_stream
Snap: rtsp://192.168.178.122:554/user=admin_password=tlJwpbo6_channel=0_stream=2&onvif=0.sdp?real_stream
```

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
- **Für Live-Vorschau auf Pi:** Sub-Stream (640×360 H.265) verwenden!
  - 4K Main-Stream verursacht Vulkan OOM, DRM-Prime-Fehler, GPU-Überlastung
  - 640×360 H.265 wird problemlos per Software dekodiert (<10% GPU)
  - **FPS muss per DVRIP auf 25 gesetzt werden** — ab Werk nur 5 FPS!
- **Für Aufnahme:** Main-Stream (4K H.265) per `ffmpeg -c:v copy` (kein Re-Encoding)

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

### Performance der ONVIF-Calls (gemessen mit diagnose/diagnose_ptz.py)
| Operation       | Durchschnitt | Min    | Max    |
|-----------------|-------------|--------|--------|
| ContinuousMove  | **19 ms**   | 15 ms  | 35 ms  |
| Stop            | **17 ms**   | 14 ms  | 30 ms  |

- Jeder Call ist ein synchroner HTTP/SOAP Request
- ~20ms ist schnell genug für **direkte synchrone Aufrufe** im Control-Loop
- Ein Worker-Thread ist **NICHT nötig** (verursacht sogar Probleme, siehe Abschnitt 8)
- Kamera hat **keinen Auto-Timeout** — ContinuousMove läuft unbegrenzt bis Stop kommt
  (getestet: 67 Sekunden durchgehende Bewegung ohne Probleme)

### ONVIF ist READ-ONLY für Konfiguration!
**SetVideoEncoderConfiguration schlägt auf dieser Kamera IMMER fehl!**
- Fehler: `"The configuration parameters are not possible to set"`
- Getestet mit allen FPS-Werten (25, 20, 15, 10), allen Auflösungen, mit/ohne Multicast/SessionTimeout
- Die Kamera akzeptiert **keine** Konfigurationsänderungen über ONVIF
- **Lösung: Konfiguration über DVRIP** (Port 34567) — siehe Abschnitt 5.2

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

### 5.2 Encoding-Konfiguration (Simplify.Encode) — FPS ändern!

Die vollständige Encoding-Config wird über `Simplify.Encode` gelesen/geschrieben.

#### Aktuelle Konfiguration (nach FPS-Fix)
```json
{
    "Simplify.Encode": [{
        "ExtraFormat": [
            {
                "Audio": {"BitRate": 10, "MaxVolume": 10, "SampleRate": 10},
                "AudioEnable": true,
                "Video": {
                    "BitRate": 106,
                    "BitRateControl": "VBR",
                    "Compression": "H.265",
                    "FPS": 25,
                    "GOP": 2,
                    "Quality": 3,
                    "Resolution": "QVGA",
                    "VirtualGOP": 1
                },
                "VideoEnable": true
            },
            {
                "Audio": {"BitRate": 10, "MaxVolume": 10, "SampleRate": 10},
                "AudioEnable": true,
                "Video": {
                    "BitRate": 106,
                    "BitRateControl": "VBR",
                    "Compression": "H.265",
                    "FPS": 25,
                    "GOP": 2,
                    "Quality": 3,
                    "Resolution": "QVGA",
                    "VirtualGOP": 1
                },
                "VideoEnable": true
            }
        ],
        "MainFormat": [
            {
                "Video": {
                    "BitRate": 6305,
                    "BitRateControl": "VBR",
                    "Compression": "H.265",
                    "FPS": 17,
                    "GOP": 2,
                    "Quality": 6,
                    "Resolution": "4K",
                    "VirtualGOP": 1
                },
                "VideoEnable": true
            }
        ],
        "SnapFormat": [
            {
                "Video": {
                    "BitRate": 512,
                    "BitRateControl": "VBR",
                    "Compression": "H.264",
                    "FPS": 1,
                    "GOP": 2,
                    "Quality": 4,
                    "Resolution": "D1"
                },
                "VideoEnable": true
            }
        ]
    }]
}
```

#### Auflösungs-Kürzel (DVRIP → Pixel)
| DVRIP-Name | Auflösung    |
|------------|--------------|
| `4K`       | 3840×2160    |
| `QVGA`     | 640×360      |
| `D1`       | 704×576      |

#### FPS ändern per DVRIP
```bash
python3 diagnose/configure_stream_xm.py
```
Das Script:
1. Liest `Simplify.Encode` Config
2. Ändert `ExtraFormat[0].Video.FPS` auf 25
3. Schreibt die gesamte Config zurück
4. Verifiziert die Änderung

**⚠️ Die FPS-Einstellung könnte bei Kamera-Neustart verloren gehen!**
Nach jedem Neustart der Kamera prüfen und ggf. erneut setzen.

#### Weitere verfügbare DVRIP-Configs
| Config-Name              | Verfügbar | Inhalt |
|--------------------------|-----------|--------|
| `Simplify.Encode`        | ✅        | Encoding aller Streams (FPS, Bitrate, Codec, Auflösung) |
| `AVEnc.Encode`           | ✅        | Identisch zu Simplify.Encode (anderer Accessor) |
| `AVEnc.EncodeStaticParam`| ✅        | H.264/H.265 Level & Profile (`Level: 41, Profile: 3`) |
| `AVEnc.SmartH264V2`      | ✅        | Smart H.264/H.265 Kompression (alle deaktiviert) |
| `Camera.Param`           | ✅        | Kamera-Parameter (Belichtung, Gain, IR-Cut, Flip, WB) |
| `Encode`                 | ❌        | Nicht verfügbar |
| `fVideo.EncodeParam`     | ❌        | Nicht verfügbar |

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

#### Problem 6: ~1 Sekunde Video-Latenz
- **Ursache:** Sub-Stream war ab Werk nur **5 FPS** — bei 5 FPS ist ~1s Latenz physikalisch unvermeidbar
- **Diagnose:** `ffprobe` zeigte `5 fps, tbr, 5 tbn` im Sub-Stream (diagnose/diagnose_latenz.py)
- **Zusatz-Erkenntnis:** Stream war H.265 (HEVC), nicht H.264 wie ONVIF behauptet!
- **Fix:** FPS per DVRIP von 5 auf 25 erhöht (siehe Abschnitt 5.2)
- **Ergebnis:** Latenz von ~1s auf **Echtzeit** reduziert

#### Latenz-Optimierungen in mpv (alle angewendet)
| Parameter | Wert | Zweck |
|-----------|------|-------|
| `rtsp_transport` | `udp` | Weniger Overhead als TCP |
| `analyzeduration` | `0` | Kein Warten auf Stream-Analyse |
| `probesize` | `1024` | Minimaler Probe-Buffer |
| `fflags` | `+nobuffer+discardcorrupt+low_delay` | Minimale Pufferung |
| `demuxer-readahead-secs` | `0` | Kein Vorauslesen |
| `vd-lavc-threads` | `1` | Single-Thread (weniger Latenz) |
| `no-correct-pts` | ja | Frames sofort anzeigen |
| `opengl-swapinterval` | `0` | Kein VSync |
| `speed` | `1.01` | Leicht beschleunigt (holt Verzögerung auf) |

#### Finale Lösung
```
mpv --fullscreen --no-audio --profile=low-latency --cache=no --cache-pause=no \
    --demuxer-lavf-o=fflags=+nobuffer+discardcorrupt+low_delay,rtsp_transport=udp,analyzeduration=0,probesize=1024 \
    --demuxer-readahead-secs=0 --interpolation=no --video-latency-hacks=yes \
    --vd-lavc-threads=1 --hwdec=no --gpu-api=opengl --force-seekable=no \
    --no-correct-pts --opengl-swapinterval=0 --speed=1.01 \
    --framedrop=decoder+vo \
    "rtsp://192.168.178.122:554/user=admin_password=tlJwpbo6_channel=0_stream=1&onvif=0.sdp?real_stream"
```
- Sub-Stream 640×360 **H.265** → Software-Decode → **funktioniert zuverlässig**
- **<10% GPU-Auslastung** auf dem Raspberry Pi
- Bild aktualisiert sich flüssig, nahezu Echtzeit
- **Voraussetzung:** Sub-Stream muss auf 25 FPS gesetzt sein (diagnose/configure_stream_xm.py)

---

## 8. PTZ-Steuerung — Probleme & Lösungen

### Problem: "EXTREM willkürliche" Steuerung
Die Kamera reagierte erratisch auf Joystick-Eingaben, keine sinnvolle Echtzeitsteuerung möglich.

### Ursachen (chronologische Diagnose)

#### Ursache 1: Software-SPI statt Hardware-SPI (spidev fehlte!)
- **Symptom:** MCP3008 ADC lieferte extrem verrauschte Werte
- **Fehlermeldung:** `SPISoftwareFallback!: failed to initialize hardware SPI, falling back to software`
- **Diagnose (diagnose/diagnose_joystick.py):**
  | | Software-SPI | Hardware-SPI |
  |---|---|---|
  | X-Jitter | **0.4221** | **0.0088** |
  | Faktor | — | **48× besser** |
- **Fix:** `pip install spidev` — gpiozero/MCP3008 nutzt dann automatisch Hardware-SPI
- **Wichtig:** `spidev` ist in requirements.txt aufgenommen

#### Ursache 2: Worker-Thread Race Condition (Hauptursache!)
Der erste Lösungsansatz war ein Worker-Thread für ONVIF-Calls. **Das war falsch:**
- Eine `_ptz_pending` Variable speicherte immer nur **den letzten Befehl**
- **Race Condition 1:** Stop überschreibt Move → Kamera reagiert nicht
- **Race Condition 2:** Move überschreibt Stop → Kamera dreht endlos weiter
- Der Worker-Thread verarbeitete veraltete Befehle, aktuelle gingen verloren

**Beweis:** Ein absoluter Minimal-Test OHNE Worker-Thread (test_ptz_minimal.py) — nur
Joystick lesen → ONVIF direkt aufrufen — funktionierte **sofort perfekt**.

#### Ursache 3 (gering): ADC-Rauschen
- Nach Hardware-SPI-Fix nur noch minimales Rauschen (Jitter 0.0088)
- Deadzone (0.12) reicht aus, keine EMA-Glättung nötig

### Lösung: Direkte synchrone ONVIF-Calls

**KEIN Worker-Thread, KEIN EMA, KEINE Hysterese** — einfach direkt:

1. **Direkte ONVIF-Calls im Control-Loop**
   - ONVIF-Calls dauern nur ~20ms (gemessen!) → blockieren den 50ms-Loop kaum
   - Kein Threading = keine Race Conditions
   - Befehl wird sofort ausgeführt, nicht in Queue gepuffert

2. **Auto-Kalibrierung beim Start**
   - 30 Samples der Joystick/Poti-Ruheposition
   - Deadzone relativ zur **tatsächlichen Mitte** (nicht fest 0.5)
   - Kompensiert Fertigungstoleranzen des Joysticks

3. **Änderungs-Schwellwert (_CHANGE_THRESH = 0.04)**
   - Neuer Move-Befehl nur bei >4% Änderung der Geschwindigkeit
   - Verhindert Spam bei Mikro-Schwankungen

4. **Periodisches Re-Send (_RESEND_INTERVAL = 1.0s)**
   - ContinuousMove wird alle 1s wiederholt (Sicherheit bei UDP-Paketverlust)

### Ergebnis
User-Zitat: **"die steuerung funktioniert JETZT GERADE nahezu PERFEKT!"**

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
  Channel 0 → Zoom-Poti (0.0 - 1.0)  [aktuell nicht angeschlossen]
  Channel 2 → Joystick Y (0.0 - 1.0, Mitte ≈ 0.5)
  Channel 3 → Joystick X (0.0 - 1.0, Mitte ≈ 0.5)

GPIO:
  Pin 17   → Joystick-Button (Pull-Up, active low)
```

### SPI: Hardware vs. Software — KRITISCH!
| | Software-SPI (Fallback) | Hardware-SPI (spidev) |
|---|---|---|
| Jitter X-Achse | 0.4221 | **0.0088** |
| Jitter Y-Achse | 0.3950 | **0.0075** |
| Noise-Floor | ±2-5 LSB | ±0.1 LSB |
| PTZ-Steuerung | **Unbrauchbar** | Perfekt |

**Hardware-SPI erfordert das `spidev` Python-Paket!**
```bash
pip install spidev
```
Ohne `spidev` fällt gpiozero/MCP3008 **stillschweigend** auf Software-SPI zurück.
Einziger Hinweis: `SPISoftwareFallback!` in stderr (leicht zu übersehen).

Diagnosetool: `python3 diagnose/diagnose_joystick.py`

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
5. **Dual-Protocol-Zwang** — ONVIF für PTZ+Streams, aber XM/DVRIP für AI+Encoding-Config. Kein einzelnes Protokoll deckt alles ab.
6. **ONVIF lügt über Codecs** — Meldet H.264 für beide Streams, tatsächlich ist es H.265 (HEVC)!
7. **ONVIF ist Read-Only für Config** — SetVideoEncoderConfiguration wird abgelehnt. FPS/Bitrate/Codec nur per DVRIP änderbar.
8. **Sub-Stream ab Werk 5 FPS** — Verursacht ~1s Latenz. Muss per DVRIP auf 25 FPS gesetzt werden.
9. **FPS-Einstellung evtl. nicht persistent** — Nach Kamera-Neustart prüfen und ggf. erneut setzen.

### Raspberry Pi-seitig
1. **Kein Hardware-Decode für 4K** — Weder V4L2 noch DRM prime funktionieren zuverlässig für 3840×2160
2. **Vulkan crasht bei großen Texturen** — `VK_ERROR_OUT_OF_HOST_MEMORY`
3. **`--untimed` zerstört RTSP** — mpv Option die bei lokalen Dateien Sinn macht, aber RTSP-Streams einfriert
4. **`--video-sync=audio` + `--no-audio`** → mpv-Fehler (sich widersprechende Optionen)
5. **`--demuxer-lavf-o` nur EINMAL** — Bei doppelter Angabe ignoriert mpv die zweite, keine Warnung
6. **`spidev` Paket MUSS installiert sein** — Ohne fällt MCP3008 auf Software-SPI zurück (48× mehr Jitter)

### Steuerungs-seitig
1. **MCP3008 ADC rauscht nur bei Software-SPI** — Mit Hardware-SPI (spidev) ist Jitter minimal (0.0088)
2. **ONVIF-Calls sind schnell genug für synchrone Aufrufe** — ~20ms, kein Worker-Thread nötig
3. **Worker-Thread verursacht Race Conditions** — Single-Slot-Queue = Stop überschreibt Move oder umgekehrt. NICHT verwenden!
4. **ContinuousMove braucht expliziten Stop** — Kamera bewegt sich endlos bis `Stop()` kommt. Hat keinen Auto-Timeout (67s getestet).

---

## 12. Diagnose-Tools

Alle Diagnose-Tools befinden sich im Ordner `diagnose/`.

### diagnose/diagnose_joystick.py
Prüft SPI-Modus (Hardware vs. Software), misst Jitter aller ADC-Kanäle:
```bash
python3 diagnose/diagnose_joystick.py
```

### diagnose/diagnose_ptz.py
Misst ONVIF PTZ-Performance (Move/Stop-Latenz, Auto-Timeout-Test):
```bash
python3 diagnose/diagnose_ptz.py
```

### diagnose/diagnose_latenz.py
Analysiert Stream-Latenz, prüft tatsächlichen Codec und FPS per ffprobe:
```bash
python3 diagnose/diagnose_latenz.py
```

### diagnose/configure_stream_xm.py
Ändert Sub-Stream FPS über DVRIP (ONVIF kann das nicht!):
```bash
python3 diagnose/configure_stream_xm.py
```

### diagnose/configure_stream.py
Versuch FPS über ONVIF zu ändern (scheitert — nur als Dokumentation behalten).

### diagnose/test_ptz_minimal.py
Absolut minimaler PTZ-Test (Joystick → ONVIF direkt, kein Threading):
```bash
python3 diagnose/test_ptz_minimal.py
```

### diagnose/test_xm_protocol.py
Test der XM/DVRIP-Verbindung und Config-Zugriffe.

### diagnose/probe_streams.py
Testet 20 verschiedene RTSP-URLs per ffprobe und zeigt welche funktionieren:
```bash
python3 diagnose/probe_streams.py
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
├── diagnose/
│   ├── configure_stream.py      # ONVIF FPS-Versuch (scheitert)
│   ├── configure_stream_xm.py   # DVRIP FPS-Konfiguration (funktioniert!)
│   ├── diagnose_joystick.py     # SPI/ADC Jitter-Messung
│   ├── diagnose_ptz.py          # ONVIF PTZ Performance-Test
│   ├── diagnose_latenz.py       # Stream-Latenz & Codec-Analyse
│   ├── probe_streams.py         # RTSP-URL-Tester
│   ├── test_ptz_minimal.py      # Minimaler PTZ-Test (ohne Threading)
│   └── test_xm_protocol.py      # XM/DVRIP Verbindungstest
├── device_debug.py              # Diagnose: Kamera-Debug
└── requirements.txt             # Python-Abhängigkeiten
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

## 16. Kamera Config — ONVIF vs. DVRIP Vergleich

### ONVIF GetVideoEncoderConfigurationOptions (Sub-Stream)
> ⚠️ Diese Daten sind **teilweise falsch** — ONVIF meldet H264, tatsächlich ist es H.265!

```json
{
    "ResolutionsAvailable": [
        {"Width": 704, "Height": 576},
        {"Width": 800, "Height": 448},
        {"Width": 352, "Height": 288},
        {"Width": 640, "Height": 360}
    ],
    "FrameRateRange": {"Min": 1, "Max": 25},
    "GovLengthRange": {"Min": 1, "Max": 300},
    "EncodingIntervalRange": {"Min": 0, "Max": 1},
    "H264ProfilesSupported": ["Baseline", "Main", "High"],
    "QualityRange": {"Min": 1, "Max": 6}
}
```

### DVRIP Simplify.Encode — Die Wahrheit
| Eigenschaft | Main-Stream | Sub-Stream | Snap-Stream |
|-------------|-------------|------------|-------------|
| **Codec** | **H.265** | **H.265** | H.264 |
| Auflösung | 3840×2160 (4K) | 640×360 (QVGA) | 704×576 (D1) |
| FPS | 17 | 25 (ab Werk: 5!) | 1 |
| Bitrate | 6305 kbps (VBR) | 106 kbps (VBR) | 512 kbps (VBR) |
| GOP | 2 | 2 | 2 |
| Quality | 6 | 3 | 4 |
| Audio | Ja (10 kbps) | Ja (10 kbps) | Nein |

### Protokoll-Fähigkeiten
| Operation | ONVIF | DVRIP |
|-----------|-------|-------|
| Stream-URLs abfragen | ✅ | ❌ |
| PTZ-Steuerung | ✅ (~20ms) | ✅ (ungetestet) |
| Encoding-Config **lesen** | ✅ (aber falsche Codec-Angaben!) | ✅ (korrekt) |
| Encoding-Config **schreiben** | ❌ (immer Fehler) | ✅ |
| AI-Tracking Config | ❌ | ✅ |
| Kamera-Parameter (Belichtung etc.) | ❌ | ✅ |