"""
ONVIF PTZ-Steuerung mit Auto-Reconnect.
"""

from onvif import ONVIFCamera
from config.config import CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD

# Modul-Variablen (werden von init() und reconnect() gesetzt)
cam = None
media_service = None
ptz_service = None
profile = None
_move_req = None
_stop_req = None
_error_count = 0
_RECONNECT_AFTER = 3


def init():
    """Erstverbindung zur Kamera herstellen. Einmal beim Start aufrufen."""
    global cam, media_service, ptz_service, profile, _move_req, _stop_req
    print("Verbinde mit Kamera über ONVIF...")
    cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
    media_service = cam.create_media_service()
    ptz_service = cam.create_ptz_service()
    profiles = media_service.GetProfiles()
    profile = profiles[0]
    _move_req = ptz_service.create_type('ContinuousMove')
    _move_req.ProfileToken = profile.token
    _stop_req = {'ProfileToken': profile.token}
    print(f"Verbunden. Profil: {profile.Name}")


def reconnect():
    """ONVIF-Verbindung komplett neu aufbauen."""
    global cam, media_service, ptz_service, profile, _move_req, _stop_req
    try:
        print("  ↻ ONVIF Reconnect...")
        cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
        media_service = cam.create_media_service()
        ptz_service = cam.create_ptz_service()
        profiles = media_service.GetProfiles()
        profile = profiles[0]
        _move_req = ptz_service.create_type('ContinuousMove')
        _move_req.ProfileToken = profile.token
        _stop_req = {'ProfileToken': profile.token}
        print("  ✓ ONVIF Reconnect erfolgreich")
        return True
    except Exception as e:
        print(f"  ✗ ONVIF Reconnect fehlgeschlagen: {e}")
        return False


def continuous_move(pan, tilt, zoom_speed):
    """PTZ-Bewegung starten."""
    global _error_count
    try:
        _move_req.Velocity = {
            'PanTilt': {'x': float(pan), 'y': float(tilt)},
            'Zoom': {'x': float(zoom_speed)}
        }
        ptz_service.ContinuousMove(_move_req)
        _error_count = 0
    except Exception as e:
        _error_count += 1
        if _error_count == 1:
            print(f"PTZ ContinuousMove Fehler: {e}")
        if _error_count >= _RECONNECT_AFTER:
            reconnect()
            _error_count = 0


def stop():
    """PTZ-Bewegung stoppen."""
    global _error_count
    try:
        ptz_service.Stop(_stop_req)
        _error_count = 0
    except Exception as e:
        _error_count += 1
        if _error_count == 1:
            print(f"PTZ Stop Fehler: {e}")
        if _error_count >= _RECONNECT_AFTER:
            reconnect()
            _error_count = 0
