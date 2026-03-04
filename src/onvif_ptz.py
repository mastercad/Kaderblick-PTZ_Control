"""
ONVIF PTZ-Steuerung mit Auto-Reconnect + Stream-URI-Erkennung.
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
_abs_move_req = None
_error_count = 0
_RECONNECT_AFTER = 3

# Erkannte Stream-URIs (von init() gefüllt)
stream_uris = {}   # {"mainStream": "rtsp://...", "subStream": "rtsp://...", ...}


def _discover_stream_uris():
    """Alle ONVIF-Profile durchgehen und deren RTSP-URIs ermitteln."""
    global stream_uris
    stream_uris = {}
    try:
        profiles = media_service.GetProfiles()
        print(f"  ONVIF-Profile gefunden: {len(profiles)}")
        for p in profiles:
            try:
                stream_setup = {
                    'Stream': 'RTP-Unicast',
                    'Transport': {'Protocol': 'RTSP'}
                }
                uri_resp = media_service.GetStreamUri({
                    'StreamSetup': stream_setup,
                    'ProfileToken': p.token,
                })
                uri = uri_resp.Uri if hasattr(uri_resp, 'Uri') else str(uri_resp)
                stream_uris[p.Name] = uri
                # Auflösung ermitteln falls möglich
                res_info = ""
                try:
                    vec = p.VideoEncoderConfiguration
                    if vec and hasattr(vec, 'Resolution'):
                        w = vec.Resolution.Width
                        h = vec.Resolution.Height
                        enc = vec.Encoding if hasattr(vec, 'Encoding') else '?'
                        res_info = f" ({w}x{h} {enc})"
                except Exception:
                    pass
                print(f"    {p.Name}{res_info}: {uri}")
            except Exception as e:
                print(f"    {p.Name}: URI-Abfrage fehlgeschlagen ({e})")
    except Exception as e:
        print(f"  ⚠ Stream-URI-Erkennung fehlgeschlagen: {e}")


def init():
    """Erstverbindung zur Kamera herstellen. Einmal beim Start aufrufen."""
    global cam, media_service, ptz_service, profile, _move_req, _stop_req, _abs_move_req
    print("Verbinde mit Kamera über ONVIF...")
    cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
    media_service = cam.create_media_service()
    ptz_service = cam.create_ptz_service()
    profiles = media_service.GetProfiles()
    profile = profiles[0]
    _move_req = ptz_service.create_type('ContinuousMove')
    _move_req.ProfileToken = profile.token
    _abs_move_req = ptz_service.create_type('AbsoluteMove')
    _abs_move_req.ProfileToken = profile.token
    _stop_req = {'ProfileToken': profile.token}
    print(f"Verbunden. Profil: {profile.Name}")
    _discover_stream_uris()


def reconnect():
    """ONVIF-Verbindung komplett neu aufbauen."""
    global cam, media_service, ptz_service, profile, _move_req, _stop_req, _abs_move_req
    try:
        print("  ↻ ONVIF Reconnect...")
        cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
        media_service = cam.create_media_service()
        ptz_service = cam.create_ptz_service()
        profiles = media_service.GetProfiles()
        profile = profiles[0]
        _move_req = ptz_service.create_type('ContinuousMove')
        _move_req.ProfileToken = profile.token
        _abs_move_req = ptz_service.create_type('AbsoluteMove')
        _abs_move_req.ProfileToken = profile.token
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


def absolute_zoom(position):
    """Zoom auf absolute Position setzen (0.0 = kein Zoom, 1.0 = max Zoom)."""
    global _error_count
    try:
        _abs_move_req.Position = {
            'Zoom': {'x': float(max(0.0, min(1.0, position)))}
        }
        ptz_service.AbsoluteMove(_abs_move_req)
        _error_count = 0
    except Exception as e:
        _error_count += 1
        if _error_count == 1:
            print(f"PTZ AbsoluteZoom Fehler: {e}")
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
