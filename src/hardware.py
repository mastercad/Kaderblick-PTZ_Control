"""
GPIO & ADC Hardware-Setup (Raspberry Pi + MCP3008).
"""

from gpiozero import MCP3008, Button
from config.config import BTN_PIN

pot     = MCP3008(channel=0)   # Zoom-Poti
joy_y   = MCP3008(channel=2)   # Joystick Y-Achse
joy_x   = MCP3008(channel=3)   # Joystick X-Achse
joy_btn = Button(BTN_PIN, pull_up=True)
