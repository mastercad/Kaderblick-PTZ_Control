"""
Bildschirm-Overlay — Aufnahme-Indikator und AI-Warnung.
"""

import threading
import tkinter as tk

import src.state as state


def ensure_running():
    """Startet das Overlay falls es nicht schon läuft."""
    if state.overlay_thread is not None and state.overlay_thread.is_alive():
        return
    state.overlay_running = True
    state.overlay_thread = threading.Thread(target=show, daemon=True)
    state.overlay_thread.start()


def show():
    """Zeigt blinkendes Aufnahme- und AI-Warnungs-Overlay."""
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.attributes('-alpha', 0.7)
    root.configure(bg='black')
    screen_width = root.winfo_screenwidth()
    w, h = 280, 100
    x = screen_width - w - 10
    y = 10
    root.geometry(f'{w}x{h}+{x}+{y}')

    rec_label = tk.Label(
        root, text='● Aufnahme PTZ',
        font=('Arial', 18, 'bold'), fg='red', bg='black'
    )
    rec_label.pack(fill='x', pady=(5, 0))

    ai_label = tk.Label(
        root, text='',
        font=('Arial', 14, 'bold'), fg='yellow', bg='black'
    )
    ai_label.pack(fill='x', pady=(2, 5))

    blink = True

    def update():
        nonlocal blink
        if not state.overlay_running and not state.ai_warning_active:
            root.destroy()
            return

        # Aufnahme-Indikator
        if state.overlay_running:
            rec_label.config(
                text='● Aufnahme PTZ',
                fg='red' if blink else 'darkred'
            )
        else:
            rec_label.config(text='', fg='black')

        # AI-Warnung
        if state.ai_warning_active:
            ai_label.config(
                text='⚠ AI-TRACKING AKTIV!' if blink else '  AI-TRACKING AKTIV!',
                fg='yellow' if blink else 'red'
            )
        else:
            ai_label.config(text='', fg='black')

        # Fenster-Größe anpassen
        if state.overlay_running and state.ai_warning_active:
            root.geometry(f'{w}x{h}+{x}+{y}')
        elif state.overlay_running or state.ai_warning_active:
            root.geometry(f'{w}x60+{x}+{y}')

        blink = not blink
        root.after(500, update)

    update()
    root.mainloop()
