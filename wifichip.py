import time
import micropython
from machine import UART, Pin
from display import Display, debug_print

class WiFiChip:
    def __init__(self, web_delay=300):
        self.WEB_DELAY = web_delay
        self.uart = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(1))
        self.uart_busy = False
        self.uart_proc_scheduled = False
        self.ap_ip = "unknown"
        self.nfc = None  # Wordt later ingesteld vanuit main.py

    def set_nfc(self, nfc_instance):
        self.nfc = nfc_instance

    def send_command(self, cmd, delay_ms=None):
        if delay_ms is None:
            delay_ms = self.WEB_DELAY
        try:
            debug_print("Sending command: " + cmd)
            self.uart.write((cmd + "\r\n").encode())
            time.sleep_ms(delay_ms)
            response = self.uart.read()
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

    def setup(self):
        self.send_command("AT", self.WEB_DELAY)
        self.send_command("AT+CWMODE=2", self.WEB_DELAY)
        self.send_command('AT+CWSAP="Hackbat_AP","hackbat123",5,3', self.WEB_DELAY)
        self.send_command("AT+CIPMUX=1", self.WEB_DELAY)
        self.send_command("AT+CIPSERVER=1,80", self.WEB_DELAY)
        print("ESP8266 is nu een Access Point met een webserver!")
        Display.update_status("ESP8266 gestart")

    def ask_ip(self):
        response = self.send_command("AT+CIFSR", self.WEB_DELAY)
        debug_print("AT+CIFSR response:\n" + str(response))
        if response:
            for line in response.splitlines():
                if "APIP" in line:
                    try:
                        self.ap_ip = line.split('"')[1]
                        debug_print("Parsed AP IP: " + self.ap_ip)
                    except Exception as e:
                        debug_print("Error parsing IP: " + str(e))
        print("Gevonden IP:", self.ap_ip)
        Display.show_ip(self.ap_ip)
        return self.ap_ip

    def process_uart(self, dummy):
        self.uart_proc_scheduled = False
        if self.uart_busy:
            debug_print("UART busy, skipping processing.")
            return
        self.uart_busy = True
        try:
            if self.uart.any():
                data = self.uart.read()
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
                            if self.nfc:
                                result = self.nfc.run_mfkey32()
                            else:
                                result = "NFC module not set"
                            file_content = ("<html><head><title>mfkey32 Resultaat</title></head><body>"
                                            "<h1>mfkey32 Resultaat</h1><pre>" + result +
                                            "</pre><br><a href='/'>Terug</a></body></html>")
                        else:
                            if self.nfc and self.nfc.current_card_info:
                                card_info = self.nfc.current_card_info
                            else:
                                card_info = "Geen kaartdata"
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
                        self.send_command('AT+CIPSEND={0},{1}'.format(link_id, len(html_response)), self.WEB_DELAY)
                        self.uart.write(html_response.encode())
                        time.sleep_ms(self.WEB_DELAY)
                        self.send_command("AT+CIPCLOSE=" + link_id, self.WEB_DELAY)
                        print("Response verzonden naar client.")
                        if self.nfc and self.nfc.current_card_info:
                            Display.update_status(self.nfc.current_card_info)
                        else:
                            Display.show_ip(self.ap_ip)
                    else:
                        Display.update_status("Ontvangen: " + tekst)
            else:
                debug_print("No UART data available.")
        except Exception as e:
            debug_print("process_uart error: " + str(e))
        self.uart_busy = False

    def uart_irq_handler(self, uart_instance):
        if not self.uart_proc_scheduled:
            self.uart_proc_scheduled = True
            try:
                micropython.schedule(self.process_uart, 0)
            except Exception as e:
                debug_print("Scheduling failed: " + str(e))
