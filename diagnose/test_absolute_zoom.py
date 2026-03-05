#!/usr/bin/env python3
"""
Test: ONVIF AbsoluteMove/RelativeMove/ContinuousMove Zoom.
Port 8899 = echter ONVIF-Service (Port 80 = nur Webserver, gibt HTML-404).

Aufruf: python3 diagnose/test_absolute_zoom.py
"""

import requests, time, sys, re, socket

CAMERA_IP = '192.168.178.122'
PORT = 8899
BASE = f'http://{CAMERA_IP}:{PORT}/onvif'
TIMEOUT = 10  # Kamera braucht manchmal laenger

NS = ('xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
      'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
      'xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl" '
      'xmlns:tt="http://www.onvif.org/ver10/schema" '
      'xmlns:trt="http://www.onvif.org/ver10/media/wsdl"')


def tcp_check(host, port, timeout=3):
    """Schneller TCP-Check ob Port offen ist."""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except:
        return False


def soap(url, body, label="", dump=False):
    envelope = (f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<s:Envelope {NS}><s:Body>{body}</s:Body></s:Envelope>')
    try:
        t0 = time.time()
        r = requests.post(url, data=envelope,
                         headers={'Content-Type': 'application/soap+xml; charset=utf-8'},
                         timeout=TIMEOUT)
        dt = (time.time() - t0) * 1000

        # Echte XML-Pruefung: HTML = Fehler, Fault = Fehler
        is_xml = '<?xml' in r.text[:100] or '<s:Envelope' in r.text[:200] or '<SOAP' in r.text[:200].upper()
        has_fault = 'Fault' in r.text
        ok = r.status_code == 200 and is_xml and not has_fault

        print(f"  {'OK' if ok else 'FAIL'} {label} ({dt:.0f}ms)")
        if dump and is_xml:
            text = r.text.replace('><', '>\n<')[:3000]
            for line in text.split('\n'):
                print(f"    {line.strip()}")
        elif not is_xml:
            print(f"    Keine XML-Antwort! Erste 200 Zeichen: {r.text[:200]}")
        if has_fault:
            fault = re.search(r'Text[^>]*>([^<]+)', r.text)
            if fault: print(f"    FAULT: {fault.group(1)}")
        return ok, r.text
    except requests.exceptions.Timeout:
        print(f"  FAIL {label} — TIMEOUT nach {TIMEOUT}s!")
        return False, ""
    except Exception as e:
        print(f"  FAIL {label} — {e}")
        return False, ""


print("=" * 60)
print("ONVIF Zoom Test")
print("=" * 60)

# TCP-Check
print(f"\nTCP-Check {CAMERA_IP}:{PORT} ... ", end="", flush=True)
if tcp_check(CAMERA_IP, PORT):
    print("OK")
else:
    print("FAIL! Port nicht erreichbar.")
    sys.exit(1)

# GetDeviceInformation — testen ob ONVIF antwortet
print("\n== GetDeviceInformation ==")
ok, _ = soap(f'{BASE}/device_service',
    '<tds:GetDeviceInformation/>', 'DeviceInfo', dump=True)
if not ok:
    print("ONVIF antwortet nicht! Evtl. Kamera neu starten?")
    sys.exit(1)

# GetCapabilities — Service-URLs
print("\n== GetCapabilities ==")
ok, resp = soap(f'{BASE}/device_service',
    '<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>',
    'GetCapabilities', dump=True)

# URLs aus Antwort
ptz_url = media_url = None
if ok:
    urls = re.findall(r'https?://[^<"\s]+', resp)
    print(f"\n  Alle URLs: {urls}")
    for u in urls:
        if 'ptz' in u.lower(): ptz_url = u
        if 'media' in u.lower(): media_url = u

if not ptz_url:
    print("  Keine PTZ-URL gefunden, versuche Standard-Pfade")
    ptz_url = f'{BASE}/ptz_service'
    media_url = f'{BASE}/media_service'

print(f"  PTZ:   {ptz_url}")
print(f"  Media: {media_url}")

# GetProfiles -> Token
print("\n== GetProfiles ==")
ok, resp = soap(media_url, '<trt:GetProfiles/>', 'GetProfiles', dump=True)
tokens = re.findall(r'token="([^"]+)"', resp) if ok else []
print(f"  Tokens: {tokens}")

if not tokens:
    print("Kein Token! Versuche PTZ GetConfigurations...")
    ok, resp = soap(ptz_url, '<tptz:GetConfigurations/>', 'PTZ Configs', dump=True)
    tokens = re.findall(r'token="([^"]+)"', resp) if ok else []

if not tokens:
    print("\nFEHLER: Kein Token gefunden!")
    sys.exit(1)

token = tokens[0]
print(f"  Verwende Token: {token}")

# GetNodes
print("\n== GetNodes ==")
ok, resp = soap(ptz_url, '<tptz:GetNodes/>', 'GetNodes', dump=True)
if ok:
    for kw in ['AbsoluteZoom', 'RelativeZoom', 'ContinuousZoom',
                'AbsolutePanTilt', 'RelativePanTilt', 'ContinuousPanTilt']:
        print(f"  {kw}: {'JA' if kw.lower() in resp.lower() else 'NEIN'}")

# GetStatus
print("\n== GetStatus ==")
soap(ptz_url,
    f'<tptz:GetStatus><tptz:ProfileToken>{token}</tptz:ProfileToken></tptz:GetStatus>',
    'GetStatus', dump=True)

# Zoom-Tests
tests = [
    ("AbsoluteMove Zoom=0.5",
     f'<tptz:AbsoluteMove><tptz:ProfileToken>{token}</tptz:ProfileToken>'
     f'<tptz:Position><tt:Zoom x="0.5"/></tptz:Position></tptz:AbsoluteMove>'),
    ("AbsoluteMove Zoom=0.0",
     f'<tptz:AbsoluteMove><tptz:ProfileToken>{token}</tptz:ProfileToken>'
     f'<tptz:Position><tt:Zoom x="0.0"/></tptz:Position></tptz:AbsoluteMove>'),
    ("RelativeMove Zoom=+0.5",
     f'<tptz:RelativeMove><tptz:ProfileToken>{token}</tptz:ProfileToken>'
     f'<tptz:Translation><tt:Zoom x="0.5"/></tptz:Translation></tptz:RelativeMove>'),
    ("RelativeMove Zoom=-0.5",
     f'<tptz:RelativeMove><tptz:ProfileToken>{token}</tptz:ProfileToken>'
     f'<tptz:Translation><tt:Zoom x="-0.5"/></tptz:Translation></tptz:RelativeMove>'),
]

for label, body in tests:
    print(f"\n== {label} ==")
    soap(ptz_url, body, label, dump=True)
    print("  Warte 3s...")
    time.sleep(3)

# ContinuousMove (Referenz — funktioniert bekannt)
print("\n== ContinuousMove Zoom=+0.5 (2s Referenz) ==")
ok, _ = soap(ptz_url,
    f'<tptz:ContinuousMove><tptz:ProfileToken>{token}</tptz:ProfileToken>'
    f'<tptz:Velocity><tt:Zoom x="0.5"/></tptz:Velocity></tptz:ContinuousMove>',
    'ContinuousMove +0.5', dump=True)
if ok:
    time.sleep(2)
    soap(ptz_url,
        f'<tptz:Stop><tptz:ProfileToken>{token}</tptz:ProfileToken>'
        f'<tptz:Zoom>true</tptz:Zoom></tptz:Stop>', 'Stop')

print("\n== ContinuousMove Zoom=-0.5 (2s) ==")
ok, _ = soap(ptz_url,
    f'<tptz:ContinuousMove><tptz:ProfileToken>{token}</tptz:ProfileToken>'
    f'<tptz:Velocity><tt:Zoom x="-0.5"/></tptz:Velocity></tptz:ContinuousMove>',
    'ContinuousMove -0.5', dump=True)
if ok:
    time.sleep(2)
    soap(ptz_url,
        f'<tptz:Stop><tptz:ProfileToken>{token}</tptz:ProfileToken>'
        f'<tptz:Zoom>true</tptz:Zoom></tptz:Stop>', 'Stop')

print("\n" + "=" * 60)
print("Fertig!")
print("=" * 60)
