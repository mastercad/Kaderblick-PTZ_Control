"""
XM Binary Protocol (DVRIP) — Verbindung & Hilfsfunktionen für Port 34567.
"""

import json
import socket
import struct
import hashlib

from config.config import CAMERA_IP, USERNAME, PASSWORD


# ── Password-Hashing ─────────────────────────────────────────
def hash_password(password):
    """XM-Kameras nutzen ein spezielles Password-Hashing."""
    m = hashlib.md5(password.encode('utf-8') if password else b"").digest()
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    return "".join(chars[(m[2*i] + m[2*i+1]) % len(chars)] for i in range(8))


# ── Paket bauen / empfangen ──────────────────────────────────
def build_packet(msg_id, session_id, data_bytes):
    """Baut ein XM/DVRIP-Paket (20 Byte Header + Daten)."""
    header = struct.pack(
        '<BBBB I I BB H I',
        0xFF, 0x00, 0x00, 0x00,
        session_id, 0, 0, 0,
        msg_id, len(data_bytes),
    )
    return header + data_bytes


def recv_response(sock, timeout=3):
    """Empfängt und parst eine XM/DVRIP-Antwort."""
    sock.settimeout(timeout)
    try:
        header = b''
        while len(header) < 20:
            chunk = sock.recv(20 - len(header))
            if not chunk:
                return None
            header += chunk
        _, _, _, _, _, _, _, _, msg_id, data_len = struct.unpack(
            '<BBBB I I BB H I', header
        )
        data = b''
        while len(data) < data_len:
            chunk = sock.recv(min(data_len - len(data), 4096))
            if not chunk:
                break
            data += chunk
        return json.loads(
            data.rstrip(b'\x00\x0a').decode('utf-8', errors='replace')
        )
    except Exception:
        return None


# ── Verbindung ───────────────────────────────────────────────
def connect_and_login():
    """
    Stellt eine XM-Verbindung her und loggt ein.
    Gibt (sock, session_id) zurück oder (None, None) bei Fehler.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((CAMERA_IP, 34567))
    except Exception:
        return None, None

    hashed_pw = hash_password(PASSWORD)
    login_data = json.dumps({
        "EncryptType": "MD5", "LoginType": "DVRIP-Web",
        "PassWord": hashed_pw, "UserName": USERNAME
    }).encode('utf-8') + b'\x0a'
    sock.sendall(build_packet(1000, 0, login_data))
    result = recv_response(sock)

    if not isinstance(result, dict) or result.get("Ret") != 100:
        sock.close()
        return None, None

    session_str = result.get("SessionID", "0x00000000")
    session_id = (
        int(session_str, 16)
        if isinstance(session_str, str) and session_str.startswith("0x")
        else 0
    )
    return sock, session_id


# ── Config lesen / schreiben ─────────────────────────────────
def get_config(sock, session_id, config_name):
    """Liest eine Konfiguration. Gibt (erfolg, daten) zurück."""
    try:
        payload = json.dumps({
            "Name": config_name,
            "SessionID": f"0x{session_id:08X}"
        }).encode('utf-8') + b'\x0a'
        sock.sendall(build_packet(1042, session_id, payload))
        resp = recv_response(sock, timeout=2)
        if isinstance(resp, dict) and resp.get("Ret") in (0, 100):
            return True, resp
        return False, resp
    except (OSError, ConnectionError):
        return False, None


def set_config(sock, session_id, config_name, config_data):
    """Setzt eine Konfiguration. Gibt True/False zurück."""
    try:
        payload = json.dumps({
            "Name": config_name,
            config_name: config_data,
            "SessionID": f"0x{session_id:08X}"
        }).encode('utf-8') + b'\x0a'
        sock.sendall(build_packet(1040, session_id, payload))
        resp = recv_response(sock, timeout=2)
        return isinstance(resp, dict) and resp.get("Ret") in (0, 100)
    except (OSError, ConnectionError):
        return False
