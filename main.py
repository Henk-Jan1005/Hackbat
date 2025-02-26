import time
import micropython
import json
from machine import Timer
import hardware_setup
from display import Display, debug_print
from nfc_module import NFCModule
from knopjes import create_buttons, menu_pressed, next_pressed, confirm_pressed
from wifichip import WiFiChip

# Globale variabelen
DEBUG = True
menu_active = False  # Wordt gebruikt om de kaartdetectie tijdelijk te pauzeren tijdens menu-activiteit

# Initialiseer NFC-module
nfc = NFCModule()

# Initialiseer WiFiChip en koppel de NFC-module
wifi = WiFiChip()
wifi.set_nfc(nfc)

# Stel de UART IRQ in zodat de WiFiChip zijn eigen process_uart kan aanroepen
wifi.uart.irq(handler=wifi.uart_irq_handler, trigger=wifi.uart.IRQ_RXIDLE, hard=False)

# Cache voor de homepagina (indien gewenst)
cached_homepage = None

# Kaartdetectie via Timer
nfc_poll_timer = Timer(-1)
def poll_for_card(timer):
    # Geef de huidige menu-status door, zodat tijdens een menu geen nieuwe kaart wordt ingelezen
    nfc.process_card_detection(menu_active)

nfc_poll_timer.init(period=1000, mode=Timer.PERIODIC, callback=lambda t: micropython.schedule(poll_for_card, 0))

# # Heartbeat Timer
# heartbeat_timer = Timer(-1)
# heartbeat_timer.init(period=1000, mode=Timer.PERIODIC, callback=lambda t: debug_print("Heartbeat tick"))

# Callback-functies voor de knoppen
def discard_card():
    nfc.current_card_info = None
    nfc.current_card_type = None
    # Leeg de gecachte data zodat een nieuwe kaart kan worden gedetecteerd
    nfc.clear_cached_data()
    Display.show_ip(wifi.ap_ip)


def emulate_card_callback():
    nfc.emulate_card()
    
def crack_card_callback():
    nfc.send_card_data_for_cracking()

def resume_polling():
    nfc_poll_timer.init(period=1000, mode=Timer.PERIODIC, callback=lambda t: micropython.schedule(poll_for_card, 0))

# Maak de fysieke knoppen aan via knopjes.py
btn_menu, btn_next, btn_confirm = create_buttons(
    menu_pressed,
    next_pressed,
    lambda btn: confirm_pressed(btn, emulate_card_callback, crack_card_callback, discard_card, resume_polling)
)

def main():
    debug_print("Starting main initialization.")
    wifi.setup()
    wifi.ask_ip()
    print("Initialisatie voltooid. Wacht op binnenkomende verbindingen...")
    while True:
        time.sleep(2)

if __name__ == "__main__":
    main()
