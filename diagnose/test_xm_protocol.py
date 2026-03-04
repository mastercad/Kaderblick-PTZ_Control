#!/usr/bin/env python3
"""
XM/Xiongmai Protokoll-Test für Hiseeu HD118-PZ
================================================
Testet ob die Kamera auf Port 34567 (XM Binary Protocol) erreichbar
ist und versucht sich einzuloggen.

Das XM-Protokoll ist WESENTLICH schneller als ONVIF für PTZ-Steuerung:
- Persistente TCP-Verbindung (kein HTTP-Overhead)
- Binäre Pakete statt XML/SOAP
- ~5-20ms pro Befehl statt 100-500ms bei ONVIF

Nutzung:
    python3 test_xm_protocol.py
"""

import socket
import struct
import json
import hashlib
import time

# --- Konfiguration ---
CAMERA_IP = '192.168.178.122'
XM_PORT = 34567       # Standard XM-Protokoll Port
USERNAME = 'admin'
PASSWORD = ''

# XM-Protokoll Konstanten
XM_HEADER = 0xFF       # Header-Byte
XM_VERSION = 0x01      # Protokoll-Version

# Message-IDs (aus XM SDK / Reverse Engineering)
LOGIN_REQ = 1000
LOGIN_RSP = 1001
PTZ_REQ = 1400
PTZ_RSP = 1401
SYSINFO_REQ = 1020
SYSINFO_RSP = 1021
CONFIG_GET = 1042
CONFIG_SET = 1040
KEEPALIVE_REQ = 1006
KEEPALIVE_RSP = 1007

# PTZ-Kommandos
PTZ_LEFT = 2
PTZ_RIGHT = 3
PTZ_UP = 0
PTZ_DOWN = 1
PTZ_ZOOM_IN = 8
PTZ_ZOOM_OUT = 9
PTZ_STOP = 14

# ============================================================
# XM Protokoll-Funktionen
# ============================================================

def xm_hash_password(password):
    """XM-Kameras nutzen ein spezielles Password-Hashing."""
    if not password:
        # Leeres Passwort → spezieller Hash
        m = hashlib.md5(b"").digest()
    else:
        m = hashlib.md5(password.encode('utf-8')).digest()

    # XM-spezifisch: Nur bestimmte Bytes des MD5-Hashes verwenden
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    result = ""
    for i in range(8):
        idx = m[2 * i] + m[2 * i + 1]
        result += chars[idx % len(chars)]
    return result


def build_xm_packet(msg_id, session_id, data_bytes):
    """
    Baut ein XM/DVRIP-Protokoll-Paket:
    Header (20 Bytes) + Daten

    Header-Layout:
      Byte  0:     0xFF (Head flag)
      Byte  1:     Version (0x00 oder 0x01)
      Byte  2-3:   Reserved (2× uint8)
      Byte  4-7:   Session ID (uint32 LE)
      Byte  8-11:  Sequence number (uint32 LE)
      Byte  12:    Total packets (uint8)
      Byte  13:    Current packet (uint8)
      Byte  14-15: Message ID (uint16 LE)
      Byte  16-19: Data length (uint32 LE)
    """
    header = struct.pack(
        '<BBBB I I BB H I',
        XM_HEADER,          # Byte 0:  Head flag
        0x00,               # Byte 1:  Version (0x00 für Login)
        0x00,               # Byte 2:  Reserved
        0x00,               # Byte 3:  Reserved
        session_id,         # Byte 4-7:  Session ID
        0,                  # Byte 8-11: Sequence
        0,                  # Byte 12: Total packets
        0,                  # Byte 13: Current packet
        msg_id,             # Byte 14-15: Message ID
        len(data_bytes),    # Byte 16-19: Data length
    )
    return header + data_bytes


def parse_xm_response(sock, timeout=5):
    """Empfängt und parst eine XM/DVRIP-Protokoll-Antwort."""
    sock.settimeout(timeout)
    try:
        # Header lesen (20 Bytes)
        header = b''
        while len(header) < 20:
            chunk = sock.recv(20 - len(header))
            if not chunk:
                return None, None, "Verbindung geschlossen"
            header += chunk

        # Header parsen
        (head_flag, version, res1, res2,
         session_id, seq,
         total_pkts, cur_pkt,
         msg_id,
         data_len) = struct.unpack('<BBBB I I BB H I', header)

        if head_flag != XM_HEADER:
            # Debug: Was kam stattdessen?
            return msg_id, session_id, (
                f"Ungültiger Header: erstes Byte={head_flag:#04x}, "
                f"raw={header[:8].hex()}"
            )

        # Daten lesen
        data = b''
        remaining = data_len
        while len(data) < remaining:
            chunk = sock.recv(min(remaining - len(data), 4096))
            if not chunk:
                break
            data += chunk

        # JSON parsen (XM sendet JSON + \x0a Terminator)
        data_str = data.rstrip(b'\x00\x0a').decode('utf-8', errors='replace')
        try:
            result = json.loads(data_str)
        except json.JSONDecodeError:
            result = data_str

        return msg_id, session_id, result

    except socket.timeout:
        return None, None, "Timeout"
    except Exception as e:
        return None, None, str(e)


# ============================================================
# Tests
# ============================================================

def test_port_reachable():
    """Test 1: Ist Port 34567 überhaupt erreichbar?"""
    print("=" * 60)
    print("Test 1: Port 34567 erreichbar?")
    print("=" * 60)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((CAMERA_IP, XM_PORT))
        sock.close()

        if result == 0:
            print(f"  ✓ Port {XM_PORT} ist OFFEN auf {CAMERA_IP}")
            return True
        else:
            print(f"  ✗ Port {XM_PORT} ist GESCHLOSSEN (errno={result})")
            return False
    except Exception as e:
        print(f"  ✗ Fehler: {e}")
        return False


def test_raw_probe():
    """Test 1b: Rohe Verbindung — was sendet die Kamera von sich aus?"""
    print()
    print("=" * 60)
    print("Test 1b: Raw-Probe — was kommt von der Kamera?")
    print("=" * 60)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((CAMERA_IP, XM_PORT))

        # Warte ob die Kamera von sich aus etwas sendet
        try:
            data = sock.recv(512)
            if data:
                print(f"  Kamera sendet {len(data)} Bytes bei Verbindung:")
                print(f"    Hex: {data[:40].hex()}")
                print(f"    Raw: {data[:60]!r}")
                if data[0] == 0xFF:
                    print("    → Sieht nach XM-Header aus (0xFF)")
                else:
                    print(f"    → Erstes Byte: {data[0]:#04x} (kein XM-Header)")
            else:
                print("  Kamera sendet nichts von sich aus (erwartet)")
        except socket.timeout:
            print("  Kamera sendet nichts von sich aus (erwartet)")

        # Sende etwas Müll und schaue was zurückkommt
        print("\n  Sende Test-Bytes...")
        sock.sendall(b'\xff\x00\x00\x00' + b'\x00' * 16)
        try:
            sock.settimeout(3)
            data = sock.recv(512)
            if data:
                print(f"  Kamera antwortet mit {len(data)} Bytes:")
                print(f"    Hex: {data[:40].hex()}")
                print(f"    Raw: {data[:60]!r}")
            else:
                print("  Keine Antwort auf Test-Bytes")
        except socket.timeout:
            print("  Timeout — keine Antwort auf Test-Bytes")

        sock.close()
    except Exception as e:
        print(f"  ✗ Fehler: {e}")


def test_login():
    """Test 2: Login über XM-Protokoll — versucht mehrere Varianten."""
    print()
    print("=" * 60)
    print("Test 2: XM-Protokoll Login")
    print("=" * 60)

    hashed_pw = xm_hash_password(PASSWORD)

    # Verschiedene Login-Varianten, da XM-Firmware-Versionen sich unterscheiden
    login_variants = [
        ("DVRIP-Web / MD5", {
            "EncryptType": "MD5",
            "LoginType": "DVRIP-Web",
            "PassWord": hashed_pw,
            "UserName": USERNAME
        }),
        ("DVRIP-Web / Plain", {
            "EncryptType": "MD5",
            "LoginType": "DVRIP-Web",
            "PassWord": PASSWORD if PASSWORD else "",
            "UserName": USERNAME
        }),
        ("DVRIP-DVR / MD5", {
            "EncryptType": "MD5",
            "LoginType": "DVRIP-DVR",
            "PassWord": hashed_pw,
            "UserName": USERNAME
        }),
        ("Ohne LoginType", {
            "EncryptType": "MD5",
            "PassWord": hashed_pw,
            "UserName": USERNAME
        }),
        ("Nur User+Pass", {
            "UserName": USERNAME,
            "PassWord": hashed_pw
        }),
    ]

    for variant_name, login_payload in login_variants:
        print(f"\n  Versuch: {variant_name}")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((CAMERA_IP, XM_PORT))

            login_data = json.dumps(login_payload).encode('utf-8') + b'\x0a'
            packet = build_xm_packet(LOGIN_REQ, 0, login_data)

            # Debug: Paket-Info
            print(f"    Paket: {len(packet)} Bytes (Header: 20 + Daten: {len(login_data)})")
            print(f"    Header hex: {packet[:20].hex()}")

            sock.sendall(packet)

            # Antwort empfangen
            msg_id, session_id, result = parse_xm_response(sock, timeout=5)

            if msg_id is None:
                print(f"    ✗ Keine Antwort: {result}")

                # Debug: Lese rohe Bytes falls vorhanden
                try:
                    sock.settimeout(1)
                    raw = sock.recv(256)
                    if raw:
                        print(f"    Debug: Rohe Bytes empfangen: {raw[:40].hex()}")
                        print(f"    Debug: Als Text: {raw[:80]!r}")
                except socket.timeout:
                    pass

                sock.close()
                continue

            print(f"    ← MsgID={msg_id}, SessionID={session_id:#010x}")

            if isinstance(result, dict):
                ret = result.get("Ret", -1)
                print(f"    Ret={ret}")
                if ret == 100:
                    print(f"    ✓ LOGIN ERFOLGREICH mit '{variant_name}'!")
                    session = result.get("SessionID", session_id)
                    if isinstance(session, str):
                        session = int(session, 16) if session.startswith("0x") else int(session)
                    print(f"    Session-ID: {session:#010x}")
                    return sock, session
                else:
                    print(f"    Antwort: {json.dumps(result, indent=2)[:200]}")
            else:
                print(f"    Antwort: {str(result)[:200]}")

            sock.close()

        except Exception as e:
            print(f"    ✗ Fehler: {e}")
            try:
                sock.close()
            except Exception:
                pass

    print(f"\n  ✗ Alle Login-Varianten fehlgeschlagen")
    return None


def test_ptz_command(sock, session_id):
    """Test 3: PTZ-Befehl senden."""
    print()
    print("=" * 60)
    print("Test 3: PTZ-Befehl Test (kurzer Links-Schwenk)")
    print("=" * 60)

    try:
        # PTZ links starten
        ptz_data = json.dumps({
            "Name": "OPPTZControl",
            "OPPTZControl": {
                "Command": "DirectionLeft",
                "Parameter": {
                    "AUX": {"Number": 0, "Status": "On"},
                    "Channel": 0,
                    "MenuOpts": "Enter",
                    "POINT": {"bottom": 0, "left": 0, "right": 0, "top": 0},
                    "Pattern": "SetBegin",
                    "Preset": 0,
                    "Step": 5,
                    "Tour": 0
                }
            }
        }).encode('utf-8') + b'\x0a'

        t_start = time.time()
        packet = build_xm_packet(PTZ_REQ, session_id, ptz_data)
        sock.sendall(packet)

        msg_id, _, result = parse_xm_response(sock)
        t_end = time.time()
        latency_ms = (t_end - t_start) * 1000

        if isinstance(result, dict) and result.get("Ret", -1) == 100:
            print(f"  ✓ PTZ-Befehl ERFOLGREICH! Latenz: {latency_ms:.1f}ms")
        else:
            print(f"  ? PTZ-Antwort: {result}")
            print(f"    Latenz: {latency_ms:.1f}ms")

        # Sofort Stop senden
        time.sleep(0.3)
        stop_data = json.dumps({
            "Name": "OPPTZControl",
            "OPPTZControl": {
                "Command": "DirectionLeftStop",
                "Parameter": {
                    "AUX": {"Number": 0, "Status": "On"},
                    "Channel": 0,
                    "MenuOpts": "Enter",
                    "POINT": {"bottom": 0, "left": 0, "right": 0, "top": 0},
                    "Pattern": "SetBegin",
                    "Preset": 0,
                    "Step": 5,
                    "Tour": 0
                }
            }
        }).encode('utf-8') + b'\x0a'

        packet = build_xm_packet(PTZ_REQ, session_id, stop_data)
        sock.sendall(packet)
        msg_id, _, result = parse_xm_response(sock)
        print(f"  ✓ Stop gesendet")

        return True

    except Exception as e:
        print(f"  ✗ Fehler: {e}")
        return False


def test_latency_comparison(sock, session_id):
    """Test 4: Latenzvergleich XM vs ONVIF."""
    print()
    print("=" * 60)
    print("Test 4: Latenzvergleich XM-Protokoll vs ONVIF")
    print("=" * 60)

    # XM-Latenz messen (10 Stop-Befehle)
    xm_times = []
    stop_data = json.dumps({
        "Name": "OPPTZControl",
        "OPPTZControl": {
            "Command": "DirectionLeftStop",
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
        }
    }).encode('utf-8') + b'\x0a'

    for i in range(10):
        t_start = time.time()
        packet = build_xm_packet(PTZ_REQ, session_id, stop_data)
        sock.sendall(packet)
        msg_id, _, result = parse_xm_response(sock, timeout=3)
        t_end = time.time()
        xm_times.append((t_end - t_start) * 1000)

    xm_avg = sum(xm_times) / len(xm_times)
    xm_min = min(xm_times)
    xm_max = max(xm_times)
    print(f"  XM-Protokoll  (10 Befehle):")
    print(f"    Durchschnitt: {xm_avg:6.1f} ms")
    print(f"    Min:          {xm_min:6.1f} ms")
    print(f"    Max:          {xm_max:6.1f} ms")

    # ONVIF-Latenz messen
    try:
        from onvif import ONVIFCamera
        cam = ONVIFCamera(CAMERA_IP, 8899, USERNAME, PASSWORD)
        ptz_service = cam.create_ptz_service()
        media_service = cam.create_media_service()
        profiles = media_service.GetProfiles()
        profile = profiles[0]

        onvif_times = []
        for i in range(10):
            t_start = time.time()
            ptz_service.Stop({'ProfileToken': profile.token})
            t_end = time.time()
            onvif_times.append((t_end - t_start) * 1000)

        onvif_avg = sum(onvif_times) / len(onvif_times)
        onvif_min = min(onvif_times)
        onvif_max = max(onvif_times)
        print(f"\n  ONVIF-Protokoll (10 Befehle):")
        print(f"    Durchschnitt: {onvif_avg:6.1f} ms")
        print(f"    Min:          {onvif_min:6.1f} ms")
        print(f"    Max:          {onvif_max:6.1f} ms")

        if xm_avg < onvif_avg:
            speedup = onvif_avg / xm_avg
            print(f"\n  → XM ist {speedup:.1f}x schneller als ONVIF")
            print(f"  → Empfehlung: PTZ-Steuerung auf XM-Protokoll umstellen")
        else:
            speedup = xm_avg / onvif_avg
            print(f"\n  → ONVIF ist {speedup:.1f}x schneller als XM")
            print(f"  → Empfehlung: Bei ONVIF bleiben!")

    except Exception as e:
        print(f"\n  ONVIF-Vergleich nicht möglich: {e}")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    print("XM/Xiongmai Protokoll-Test")
    print(f"Kamera: {CAMERA_IP}:{XM_PORT}")
    print()

    # Test 1: Port erreichbar?
    if not test_port_reachable():
        print()
        print("Port 34567 ist nicht erreichbar.")
        print("Mögliche Ursachen:")
        print("  - Kamera nutzt anderen Port (z.B. 34568)")
        print("  - Firewall blockiert den Port")
        print("  - Kamera unterstützt kein XM-Protokoll")

        # Versuche alternative Ports
        print()
        print("Teste alternative Ports...")
        for port in [34568, 5000, 8000, 8080, 9000, 9527]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                if s.connect_ex((CAMERA_IP, port)) == 0:
                    print(f"  ✓ Port {port} ist OFFEN")
                s.close()
            except Exception:
                pass

        exit(1)

    # Test 1b: Raw-Probe
    test_raw_probe()

    # Test 2: Login
    login_result = test_login()
    if login_result is None:
        print()
        print("Login fehlgeschlagen.")
        print("Bitte teile die Debug-Ausgabe oben — insbesondere die")
        print("Hex-Dumps und Header-Informationen helfen bei der Analyse.")
        exit(1)

    sock, session_id = login_result

    # Test 3: PTZ-Befehl
    test_ptz_command(sock, session_id)

    # Test 4: Latenzvergleich
    test_latency_comparison(sock, session_id)

    # Verbindung schließen
    sock.close()

    print()
    print("=" * 60)
    print("FAZIT")
    print("=" * 60)
    print("Das schnellere Protokoll sollte für PTZ genutzt werden.")
    print("Falls ONVIF schneller ist → kein Wechsel nötig.")
    print("Die Video-Latenz (Vorschau) ist unabhängig vom PTZ-Protokoll")
    print("und wird durch Sub-Stream + mpv Low-Latency gelöst.")
