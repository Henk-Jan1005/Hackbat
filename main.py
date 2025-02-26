import time
import micropython
import json
from machine import UART, Pin, Timer
import hardware_setup
from display import Display, debug_print
from nfc_module import NFCModule
from knopjes import create_buttons, menu_pressed, next_pressed, confirm_pressed

# Globale variabelen
DEBUG = True
WEB_DELAY = 300
ap_ip = "unknown"

# Initialiseer NFC-module
nfc = NFCModule()

# UART-configuratie voor ESP8266
uart = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(1))
uart_busy = False
uart_proc_scheduled = False

# Cache voor de homepagina (indien gewenst)
cached_homepage = None

def send_command(cmd, delay_ms=WEB_DELAY):
    try:
        debug_print("Sending command: " + cmd)
        uart.write((cmd + "\r\n").encode())
        time.sleep_ms(delay_ms)
        response = uart.read()
        if response:
            try:
                decoded = response.decode().strip()
                debug_print("Received response: " + decoded)
                return decoded
            except Exception as e:
                debug_print("Error decoding response: " + str(e))
                return response
        else:
            debug_print("No response received for command: " + cmd)
    except Exception as e:
        debug_print("send_command exception: " + str(e))
    return ""

def setup_esp8266():
    send_command("AT", WEB_DELAY)
    send_command("AT+CWMODE=2", WEB_DELAY)
    send_command('AT+CWSAP="Hackbat_AP","hackbat123",5,3', WEB_DELAY)
    send_command("AT+CIPMUX=1", WEB_DELAY)
    send_command("AT+CIPSERVER=1,80", WEB_DELAY)
    print("ESP8266 is nu een Access Point met een webserver!")
    Display.update_status("ESP8266 gestart")

def ask_ip():
    global ap_ip
    response = send_command("AT+CIFSR", WEB_DELAY)
    debug_print("AT+CIFSR response:\n" + str(response))
    if response:
        for line in response.splitlines():
            if "APIP" in line:
                try:
                    ap_ip = line.split('"')[1]
                    debug_print("Parsed AP IP: " + ap_ip)
                except Exception as e:
                    debug_print("Error parsing IP: " + str(e))
    print("Gevonden IP:", ap_ip)
    Display.show_ip(ap_ip)
    return ap_ip

# UART & Webserver verwerking
def process_uart(dummy):
    global uart_busy, uart_proc_scheduled
    uart_proc_scheduled = False
    if uart_busy:
        debug_print("UART busy, skipping processing.")
        return
    uart_busy = True
    try:
        if uart.any():
            data = uart.read()
            debug_print("UART data length: " + str(len(data) if data else 0))
            if data:
                try:
                    tekst = data.decode()
                except Exception as e:
                    debug_print("Error decoding UART data: " + str(e))
                    tekst = str(data)
                print("UART ontvangen:", tekst)
                if "+IPD" in tekst:
                    debug_print("HTTP request detected.")
                    lines = tekst.splitlines()
                    ipd_line = None
                    for line in lines:
                        if line.startswith("+IPD"):
                            ipd_line = line
                            break
                    if ipd_line is None:
                        ipd_line = tekst
                    fields = ipd_line.split(',')
                    if len(fields) >= 2:
                        link_id = fields[1].split(":")[0].strip()
                    else:
                        link_id = "0"
                    debug_print("Extracted link ID: " + link_id)
                    print("Binnenkomende verbinding op link ID:", link_id)
                    Display.show_connected()
                    
                    if "action=mfkey32" in tekst:
                        result = nfc.run_mfkey32()
                        file_content = ("<html><head><title>mfkey32 Resultaat</title></head><body>"
                                        "<h1>mfkey32 Resultaat</h1><pre>" + result +
                                        "</pre><br><a href='/'>Terug</a></body></html>")
                    else:
                        card_info = nfc.current_card_info if nfc.current_card_info else "Geen kaartdata"
                        card_info_html = card_info.replace("\n", "<br>")
                        file_content = """<!DOCTYPE html>
<html>
<head>
  <title>Hackbat Webinterface</title>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <h1>Hackbat Webinterface</h1>
  <p>Kaartinformatie:<br>%s</p>
  <button onclick="triggerMfkey32()">Run mfkey32</button>
  <script>
    function triggerMfkey32() {
      var xhr = new XMLHttpRequest();
      xhr.open("GET", "/?action=mfkey32", true);
      xhr.onreadystatechange = function() {
        if (xhr.readyState == 4 && xhr.status == 200) {
          document.body.innerHTML = xhr.responseText;
        }
      }
      xhr.send();
    }
  </script>
</body>
</html>
""" % (card_info_html)
                    html_response = ("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                                     "Connection: close\r\n\r\n" + file_content)
                    send_command('AT+CIPSEND={0},{1}'.format(link_id, len(html_response)), WEB_DELAY)
                    uart.write(html_response.encode())
                    time.sleep_ms(WEB_DELAY)
                    send_command("AT+CIPCLOSE=" + link_id, WEB_DELAY)
                    print("Response verzonden naar client.")
                    if nfc.current_card_info:
                        Display.update_status(nfc.current_card_info)
                    else:
                        Display.show_ip(ap_ip)
                else:
                    Display.update_status("Ontvangen: " + tekst)
        else:
            debug_print("No UART data available.")
    except Exception as e:
        debug_print("process_uart error: " + str(e))
    uart_busy = False

def uart_irq_handler(uart_instance):
    global uart_proc_scheduled
    if not uart_proc_scheduled:
        uart_proc_scheduled = True
        try:
            micropython.schedule(process_uart, 0)
        except Exception as e:
            debug_print("Scheduling failed: " + str(e))

uart.irq(handler=uart_irq_handler, trigger=UART.IRQ_RXIDLE, hard=False)

# Kaartdetectie via Timer
nfc_poll_timer = Timer(-1)
def poll_for_card(timer):
    # Geef de huidige menu status door (zodat er niet tijdens een menu nieuwe kaart wordt ingelezen)
    nfc.process_card_detection(menu_active)

nfc_poll_timer.init(period=1000, mode=Timer.PERIODIC, callback=lambda t: micropython.schedule(poll_for_card, 0))

# Heartbeat Timer
heartbeat_timer = Timer(-1)
heartbeat_timer.init(period=1000, mode=Timer.PERIODIC, callback=lambda t: debug_print("Heartbeat tick"))

# Callback-functies voor de knoppen
def discard_card():
    nfc.current_card_info = None
    nfc.current_card_type = None
    Display.show_ip(ap_ip)

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
    setup_esp8266()
    ask_ip()
    print("Initialisatie voltooid. Wacht op binnenkomende verbindingen...")
    while True:
        time.sleep(2)

if __name__ == "__main__":
    main()
