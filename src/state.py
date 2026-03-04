"""
Geteilter Zustand — alle veränderbaren Globals an einem Ort.

Zugriff immer über:
    import src.state as state

Dann:
    state.recording = True
    if state.running: ...

So sehen ALLE Module sofort den aktuellen Wert.
"""

recording = False
running = True
stream_proc = None
ffmpeg_proc = None
overlay_thread = None
overlay_running = False
ai_warning_active = False
