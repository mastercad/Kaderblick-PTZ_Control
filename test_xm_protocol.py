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
    Baut ein XM-Protokoll-Paket:
    Header (20 Bytes) + Daten
    """
    head_flag = XM_HEADER
    version = XM_VERSION
    reserved1 = 0
    reserved2 = 0
    seq = 0
    total_len = len(data_bytes)

    # 20-Byte Header: head_flag(1) + version(1) + reserved(2) +
    #                 session_id(4) + seq(4) + total_len(4) + msg_id(2) + reserved(2)
    header = struct.pack('<BBHI IIH H',
                         head_flag, version, reserved1,
                         session_id,
                         seq,
                         total_len,
                         msg_id,
                         reserved2)
    return header + data_bytes


def parse_xm_response(sock, timeout=5):
    """Empfängt und parst eine XM-Protokoll-Antwort."""
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
        (head_flag, version, reserved1,
         session_id, seq, total_len,
         msg_id, reserved2) = struct.unpack('<BBHI IIH H', header)

        if head_flag != XM_HEADER:
            return msg_id, session_id, f"Ungültiger Header: {head_flag:#x}"

        # Daten lesen
        data = b''
        while len(data) < total_len:
            chunk = sock.recv(total_len - len(data))
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


def test_login():
    """Test 2: Login über XM-Protokoll."""
    print()
    print("=" * 60)
    print("Test 2: XM-Protokoll Login")
    print("=" * 60)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((CAMERA_IP, XM_PORT))
        print(f"  ✓ TCP-Verbindung hergestellt")

        # Login-Request bauen
        hashed_pw = xm_hash_password(PASSWORD)
        login_data = json.dumps({
            "EncryptType": "MD5",
            "LoginType": "DVRIP-Web",
            "PassWord": hashed_pw,
            "UserName": USERNAME
        }).encode('utf-8') + b'\x0a'

        packet = build_xm_packet(LOGIN_REQ, 0, login_data)
        sock.sendall(packet)
        print(f"  → Login-Request gesendet (User: {USERNAME})")

        # Antwort empfangen
        msg_id, session_id, result = parse_xm_response(sock)

        if msg_id is None:
            print(f"  ✗ Keine Antwort: {result}")
            sock.close()
            return None

        print(f"  ← Antwort: MsgID={msg_id}, SessionID={session_id:#x}")

        if isinstance(result, dict):
            ret = result.get("Ret", -1)
            if ret == 100:
                print(f"  ✓ LOGIN ERFOLGREICH!")
                print(f"    Session-ID: {session_id:#010x}")
                alvl = result.get("AuthorityList", [])
                if alvl:
                    print(f"    Berechtigungen: {alvl}")
                return sock, session_id
            else:
                print(f"  ✗ Login fehlgeschlagen: Ret={ret}")
                print(f"    Antwort: {json.dumps(result, indent=2)[:300]}")
        else:
            print(f"  ? Unerwartete Antwort: {result}")

        sock.close()
        return None

    except Exception as e:
        print(f"  ✗ Fehler: {e}")
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

        speedup = onvif_avg / xm_avg if xm_avg > 0 else 0
        print(f"\n  → XM ist {speedup:.1f}x schneller als ONVIF!")

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

    # Test 2: Login
    login_result = test_login()
    if login_result is None:
        print()
        print("Login fehlgeschlagen. XM-Protokoll möglicherweise")
        print("nicht kompatibel oder Zugangsdaten falsch.")
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
    print("Wenn die Tests erfolgreich waren, kann die PTZ-Steuerung")
    print("in main.py auf das XM-Protokoll umgestellt werden.")
    print("Das würde die Reaktionszeit drastisch verbessern.")
