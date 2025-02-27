import time
import micropython
from machine import UART, Pin
from display import Display, debug_print

import os



class WiFiChip:
    def __init__(self, web_delay=300):
        self.WEB_DELAY = web_delay
        self.uart = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(1))
        self.uart_busy = False
        self.uart_proc_scheduled = False
        self.ap_ip = "unknown"
        self.nfc = None  # Wordt later ingesteld vanuit main.py
        self.http_buffer = b""

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
        print("process_uart called with arg =", dummy)
        self.uart_proc_scheduled = False
        if self.uart_busy:
            debug_print("UART busy, skipping processing.")
            return
        self.uart_busy = True

        try:
            # Blijf data lezen en bufferen
            while self.uart.any():
                chunk = self.uart.read()
                if not chunk:
                    break
                debug_print("Read chunk of length: " + str(len(chunk)))
                self.http_buffer += chunk

            debug_print("Current HTTP buffer (raw): " + repr(self.http_buffer))
            
            # Als er geen 'GET ' of 'POST ' in de buffer zit en de buffer kleiner is dan 50 bytes, wacht op meer data.
            if (b"GET " not in self.http_buffer and b"POST " not in self.http_buffer) and len(self.http_buffer) < 50:
                debug_print("Not enough data to parse, waiting for next chunk.")
                self.uart_busy = False
                return

            try:
                tekst = self.http_buffer.decode()
            except Exception as e:
                debug_print("Error decoding buffer: " + str(e))
                self.http_buffer = b""
                self.uart_busy = False
                return
            print("Complete request:\n", tekst)
            # Reset de buffer na decodering
            self.http_buffer = b""

            # Splits de regels
            lines = tekst.splitlines()
            ipd_line = None
            request_line = None

            # Zoek eerst de +IPD regel
            for l in lines:
                if l.startswith("+IPD"):
                    ipd_line = l
                    break

            # Zoek naar een regel die "GET " of "POST " bevat, ook als dat niet aan het begin staat.
            for l in lines:
                if "GET " in l or "POST " in l:
                    # Neem het deel vanaf "GET " of "POST "
                    idx = l.find("GET ")
                    if idx == -1:
                        idx = l.find("POST ")
                    request_line = l[idx:]
                    break

            if not ipd_line:
                debug_print("No +IPD line found, ignoring request.")
                self.uart_busy = False
                return
            if not request_line:
                debug_print("No request line found (no GET/POST).")
                self.uart_busy = False
                return

            # Haal de link_id uit de +IPD regel
            fields = ipd_line.split(',')
            if len(fields) >= 2:
                link_id = fields[1].split(":")[0].strip()
            else:
                link_id = "0"
            debug_print("Extracted link ID: " + link_id)
            print("Binnenkomende verbinding op link ID:", link_id)
            Display.show_connected()

            # Parse de request regel, bijv. "GET / HTTP/1.1"
        # Parse de request regel, bijvoorbeeld "GET /files HTTP/1.1"
            parts = request_line.split()
            if len(parts) < 2:
                debug_print("Request line incomplete.")
                self.uart_busy = False
                return
            method = parts[0]
            path = parts[1]  # Bijvoorbeeld "/Packet.js", "/?action=mfkey32", "/files", of "/"

            if path == "/files":
                self.serve_file_list(link_id)
            elif path.endswith(".js"):
                filename = path.lstrip("/")
                self.serve_file(link_id, filename, content_type="application/javascript")
            elif "action=mfkey32" in path:
                self.serve_mfkey32(link_id)
            elif path == "/" or path.startswith("/?"):
                self.serve_index(link_id)
            else:
                self.send_not_found(link_id)

        except Exception as e:
            debug_print("process_uart error: " + str(e))
        self.uart_busy = False



    def serve_file_list(self, link_id):
        try:
            files = os.listdir("/")  # Of een ander pad indien nodig
            file_list = "<br>".join(files)
            response_body = "<html><body><h1>Bestanden</h1><p>" + file_list + "</p></body></html>"
            encoded = response_body.encode("utf-8")
            length = len(encoded)
            response_header = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html\r\n"
                "Content-Length: " + str(length) + "\r\n"
                "Connection: close\r\n\r\n"
            )
            full_response = response_header.encode("utf-8") + encoded
            self.send_command(f"AT+CIPSEND={link_id},{len(full_response)}", self.WEB_DELAY)
            self.uart.write(full_response)
            time.sleep_ms(self.WEB_DELAY)
            self.send_command(f"AT+CIPCLOSE={link_id}", self.WEB_DELAY)
            print("Response verzonden naar client (bestandlijst).")
        except Exception as e:
            debug_print("serve_file_list error: " + str(e))
            self.send_not_found(link_id)




    def serve_file(self, link_id, filename, content_type="application/javascript"):
        try:
            print("Trying to serve file:", filename)
            with open(filename, "r") as f:
                file_content = f.read()
            print("File content (first 100 chars):", file_content[:100])
            encoded_content = file_content.encode("utf-8")
            length = len(encoded_content)
            response_header = (
                "HTTP/1.1 200 OK\r\n"
                f"Content-Type: {content_type}\r\n"
                f"Content-Length: {length}\r\n"
                "Connection: close\r\n\r\n"
            )
            header_bytes = response_header.encode("utf-8")
            full_response = header_bytes + encoded_content

            # Definieer een chunk size die ondersteund wordt (bijvoorbeeld 1024 bytes)
            CHUNK_SIZE = 1024
            total_len = len(full_response)
            sent = 0
            while sent < total_len:
                chunk = full_response[sent:sent+CHUNK_SIZE]
                # Verstuur de AT+CIPSEND opdracht met de lengte van de huidige chunk
                self.send_command(f"AT+CIPSEND={link_id},{len(chunk)}", self.WEB_DELAY)
                self.uart.write(chunk)
                time.sleep_ms(self.WEB_DELAY)
                sent += len(chunk)
                print(f"Sent {sent} van {total_len} bytes")
            
            self.send_command(f"AT+CIPCLOSE={link_id}", self.WEB_DELAY)
            print("Response verzonden naar client (file).")
        except Exception as e:
            debug_print("serve_file error: " + str(e))
            self.send_not_found(link_id)




    def serve_index(self, link_id):
        try:
            with open("index.html", "r") as f:
                page = f.read()
            # Gebruik de functie om de HTML-tabel met volledige kaartdata te verkrijgen
            if self.nfc:
                card_info_html = self.nfc.get_mfkey32_data_table()
            else:
                card_info_html = "Geen kaartdata"
            file_content = page.replace("{{CARD_INFO}}", card_info_html)
            encoded = file_content.encode("utf-8")
            length = len(encoded)
            response_header = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html\r\n"
                "Content-Length: " + str(length) + "\r\n"
                "Connection: close\r\n\r\n"
            )
            full_response = response_header.encode("utf-8") + encoded
            self.send_command(f"AT+CIPSEND={link_id},{len(full_response)}", self.WEB_DELAY)
            self.uart.write(full_response)
            time.sleep_ms(self.WEB_DELAY)
            self.send_command(f"AT+CIPCLOSE={link_id}", self.WEB_DELAY)
            print("Response verzonden naar client (index).")
        except Exception as e:
            debug_print("serve_index error: " + str(e))
            self.send_not_found(link_id)


    def serve_mfkey32(self, link_id):
        if self.nfc:
            result = self.nfc.run_mfkey32()
        else:
            result = "NFC module not set"
        try:
            with open("mfkey32.html", "r") as f:
                page = f.read()
            file_content = page.replace("{{MFKEY32_RESULT}}", str(result))
            encoded = file_content.encode()
            length = len(encoded)
            response_header = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html\r\n"
                f"Content-Length: {length}\r\n"
                "Connection: close\r\n\r\n"
            )
            full_response = response_header + file_content
            self.send_command(f"AT+CIPSEND={link_id},{len(full_response)}", self.WEB_DELAY)
            self.uart.write(full_response.encode())
            time.sleep_ms(self.WEB_DELAY)
            self.send_command(f"AT+CIPCLOSE={link_id}", self.WEB_DELAY)
            print("Response verzonden naar client (mfkey32).")
        except Exception as e:
            debug_print("serve_mfkey32 error: " + str(e))
            self.send_not_found(link_id)


    def send_not_found(self, link_id):
        body = "<html><body><h1>404 Not Found</h1></body></html>"
        response_header = (
            "HTTP/1.1 404 Not Found\r\n"
            "Content-Type: text/html\r\n"
            "Connection: close\r\n\r\n"
        )
        full_response = response_header + body
        self.send_command(f"AT+CIPSEND={link_id},{len(full_response)}", self.WEB_DELAY)
        self.uart.write(full_response.encode())
        time.sleep_ms(self.WEB_DELAY)
        self.send_command(f"AT+CIPCLOSE={link_id}", self.WEB_DELAY)


    def uart_irq_handler(self, uart_instance):
        if not self.uart_proc_scheduled:
            self.uart_proc_scheduled = True
            try:
                micropython.schedule(self.process_uart, 0)
            except Exception as e:
                debug_print("Scheduling failed: " + str(e))


    def serve_carddata(self, link_id):
        import json
        data = self.nfc.get_mfkey32_data()
        if data is None:
            response_body = json.dumps({"error": "Geen kaartdata beschikbaar."})
        else:
            response_body = json.dumps(data)
        encoded = response_body.encode("utf-8")
        length = len(encoded)
        response_header = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {length}\r\n"
            "Connection: close\r\n\r\n"
        )
        full_response = response_header.encode("utf-8") + encoded
        self.send_command(f"AT+CIPSEND={link_id},{len(full_response)}", self.WEB_DELAY)
        self.uart.write(full_response)
        time.sleep_ms(self.WEB_DELAY)
        self.send_command(f"AT+CIPCLOSE={link_id}", self.WEB_DELAY)

