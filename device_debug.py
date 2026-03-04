from gpiozero import MCP3008, Button
import time

BTN_PIN = 17  # BCM
pot = MCP3008(channel=0)
joy_y = MCP3008(channel=2)
joy_x = MCP3008(channel=3)
joy_btn = Button(BTN_PIN, pull_up=True)


try:
    while True:
        x_val = joy_x.raw_value    # roher MCP3008 Wert 0..1023
        y_val = joy_y.raw_value    # roher MCP3008 Wert 0..1023
        pot_val = pot.raw_value    # roher MCP3008 Wert 0..1023
        print(f"Joystick X: {x_val:4d}, Y: {y_val:4d}, Poti: {pot_val:4d}")
        time.sleep(0.1)
except KeyboardInterrupt:
    print("Debug beendet.")
