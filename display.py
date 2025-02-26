import time
import hardware_setup

DEBUG = True
debug_buffer = []

def debug_print(message):
    if DEBUG:
        print("[DEBUG]", message)
        debug_buffer.append(message)

class Display:
    @staticmethod
    def clear():
        hardware_setup.ssd.fill(0)

    @staticmethod
    def update_status(message):
        Display.clear()
        max_chars = 16  # Tekens per regel
        line_height = 10
        y = 0
        for line in message.split('\n'):
            for i in range(0, len(line), max_chars):
                hardware_setup.ssd.text(line[i:i+max_chars], 0, y, 1)
                y += line_height
        hardware_setup.ssd.show()
        print("Display status:", message)

    @staticmethod
    def show_ip(ap_ip):
        Display.clear()
        hardware_setup.ssd.text("SSID: Hackbat_AP", 0, 0, 1)
        hardware_setup.ssd.text("IP: " + ap_ip, 0, 10, 1)
        hardware_setup.ssd.text("Wachten op", 0, 20, 1)
        hardware_setup.ssd.text("verbinding...", 0, 30, 1)
        hardware_setup.ssd.show()
        print("Display: IP-scherm getoond.")

    @staticmethod
    def show_connected():
        Display.clear()
        hardware_setup.ssd.text("Client Connected!", 0, 0, 1)
        hardware_setup.ssd.show()
        print("Display: Connected-scherm getoond.")
