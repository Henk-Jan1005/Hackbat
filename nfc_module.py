import time
import json
from machine import I2C, Pin
from i2c import PN532_I2C
from display import Display, debug_print

COMMAND_INLISTPASSIVETARGET = 0x4A

class NFCModule:
    def __init__(self):
        self.i2c = I2C(0, scl=Pin(5), sda=Pin(4))
        self.pn532 = PN532_I2C(self.i2c, debug=True)
        self.pn532.SAM_configuration()
        self.cached_card_data = None  # Cache voor volledige kaartdata
        self.current_card_uid = None
        self.current_card_atqa = None
        self.current_card_sak = None
        self.current_card_info = None
        self.current_card_type = None
        # Eventuele extra initialisaties...


    def get_mfkey32_data_table(self):
        """
        Haal de volledige mfkey32-data op en retourneer deze als een HTML-tabel.
        De data moet de volgende velden bevatten: uid, nt, nr0, ar0, nt1, nr1, ar1.
        """
        data = self.get_mfkey32_data()  # Zorg dat deze functie een dict retourneert met de vereiste velden
        if data is None:
            return "<p>Geen kaartdata beschikbaar.</p>"
        
        html = "<table>"
        html += "<tr><th>Parameter</th><th>Waarde</th></tr>"
        html += f"<tr><td>UID</td><td>{data.get('uid','')}</td></tr>"
        html += f"<tr><td>NT</td><td>{data.get('nt','')}</td></tr>"
        html += f"<tr><td>NR0</td><td>{data.get('nr0','')}</td></tr>"
        html += f"<tr><td>AR0</td><td>{data.get('ar0','')}</td></tr>"
        html += f"<tr><td>NT1</td><td>{data.get('nt1','')}</td></tr>"
        html += f"<tr><td>NR1</td><td>{data.get('nr1','')}</td></tr>"
        html += f"<tr><td>AR1</td><td>{data.get('ar1','')}</td></tr>"
        html += "</table>"
        return html

    def read_full_card(self):
        """Leest de volledige kaart uit (MIFARE Classic 1K) – behoudt je bestaande methode."""
        card_dump = {}
        try:
            uid = self.pn532.read_passive_target(timeout=1000)
        except Exception as e:
            debug_print("Error reading UID: " + str(e))
            return None
        if uid is None:
            print("Geen kaart gevonden.")
            return None
        uid_str = ' '.join("{:02X}".format(x) for x in uid)
        print("Kaart UID:", uid_str)
        card_dump['uid'] = uid
        sectors = {}
        SECTORS = 16
        BLOCKS_PER_SECTOR = 4
        DEFAULT_KEY_A = b'\xFF\xFF\xFF\xFF\xFF\xFF'
        for sector in range(SECTORS):
            trailer_block = (sector + 1) * BLOCKS_PER_SECTOR - 1
            print(f"Authenticatie voor sector {sector} (trailer block {trailer_block})...")
            try:
                auth_success = self.pn532.mifare_classic_authenticate_block(uid, trailer_block, 0x60, DEFAULT_KEY_A)
            except Exception as e:
                debug_print("Auth exception in sector {}: {}".format(sector, e))
                continue
            if not auth_success:
                print(f"  Authenticatie mislukt voor sector {sector}.")
                continue
            trailer = self.pn532.mifare_classic_read_block(trailer_block)
            first_data_block = sector * BLOCKS_PER_SECTOR
            data_block = self.pn532.mifare_classic_read_block(first_data_block)
            sectors[sector] = {'trailer': trailer, 'data': data_block}
            print("  Trailer:", ' '.join("{:02X}".format(b) for b in trailer))
            if data_block:
                print("  Data   :", ' '.join("{:02X}".format(b) for b in data_block))
        card_dump['sectors'] = sectors
        return card_dump

    def send_card_data_for_cracking(self):
        card_dump = self.read_full_card()
        if card_dump:
            data_json = json.dumps(card_dump)
            Display.update_status("Kaartdata voor mfkey32 verzonden!")
            print("Kaartdata voor mfkey32:", data_json)
            return data_json
        else:
            Display.update_status("Capture failed!")
            return None

    def emulate_card(self):
        if self.current_card_uid and self.current_card_atqa and self.current_card_sak:
            uid_str = ' '.join("{:02X}".format(x) for x in self.current_card_uid)
            Display.update_status("Emulating:\n" + uid_str)
            print("Emulating card with UID:", uid_str)
            params = bytearray()
            params.append(0x00)
            params.extend(self.current_card_atqa)
            params.append(self.current_card_sak)
            params.append(len(self.current_card_uid))
            params.extend(self.current_card_uid)
            try:
                response = self.pn532.tginitastarget(params, timeout=1000)
                print("Target mode started, response:", response)
            except RuntimeError as e:
                if "Received unexpected command response" in str(e):
                    print("Target mode started (ignoring error).")
                else:
                    print("Error starting target mode:", e)
            time.sleep(0.3)
        else:
            Display.update_status("Geen kaart UID!")

    def process_card_detection(self, menu_active):
        try:
            if self.cached_card_data is not None:
                return
            if not self.pn532.listen_for_passive_target(timeout=500) or menu_active:
                return
            response = self.pn532.process_response(COMMAND_INLISTPASSIVETARGET, 30, 500)
            if response is None or response[0] != 0x01:
                return
            uid_len = response[5]
            if uid_len > 7:
                raise RuntimeError("Kaart met te lange UID gevonden!")
            uid = response[6:6+uid_len]
            self.current_card_uid = uid
            self.current_card_atqa = response[2:4]
            self.current_card_sak = response[4]
            uid_str = ' '.join("{:02X}".format(x) for x in uid)
            atqa_str = ' '.join("{:02X}".format(x) for x in self.current_card_atqa)
            card_type_map = {"0x8": "MIFARE Classic 1K",
                             "0x18": "MIFARE Classic 4K",
                             "0x0":  "MIFARE Ultralight",
                             "0x4":  "MIFARE Ultralight",
                             "0x10": "MIFARE Plus",
                             "0x28": "MIFARE DESFire"}
            self.current_card_type = card_type_map.get(hex(self.current_card_sak), "Unknown")
            self.current_card_info = "UID: " + uid_str + "\nATQA: " + atqa_str + "\nType: " + self.current_card_type

            self.cached_card_data = self.read_full_card()
            Display.update_status(self.current_card_info)
            print("Found card with UID:", uid_str, "ATQA:", atqa_str, "Type:", self.current_card_type)
        except Exception as e:
            debug_print("Error reading card: " + str(e))

    def capture_auth_data(self, block_number, timeout=2000):
        if self.current_card_uid is None:
            print("Geen kaart UID beschikbaar voor target mode capture.")
            return None
        # Bouw parameters op volgens de target mode specificaties:
        params = bytearray()
        params.append(0x04)  # Gebruik 0x04 als mode voor target mode (niet 0x00)
        params.extend(self.current_card_atqa)  # ATQA (2 bytes, bijvoorbeeld [0x00, 0x04])
        params.append(self.current_card_sak)    # SAK (1 byte, bijvoorbeeld 0x08)
        params.append(len(self.current_card_uid)) # UID length (1 byte, bijv. 4)
        params.extend(self.current_card_uid)      # UID bytes

        init_resp = self.pn532.tginitastarget(params, timeout=1000)
        if init_resp is None:
            print("tginitastarget failed")
            return None
        print("tginitastarget response:", init_resp)
        time.sleep(1)  # Even wachten op data

        raw_data = bytearray()
        start_time = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start_time) < timeout:
            frame = self.pn532.tggetdata(timeout=500)
            if frame is None or len(frame) == 0:
                time.sleep_ms(100)
                continue
            print("Ontvangen frame:", frame)
            raw_data.extend(frame)
            if len(raw_data) >= 12:  # Verwacht 12 bytes: 4 voor nt, 4 voor nr, 4 voor ar
                break
            time.sleep_ms(100)
        if len(raw_data) < 12:
            print("Niet genoeg data ontvangen in target mode.")
            return None
        print("Volledige target mode raw data:", raw_data)
        return raw_data

    def get_mfkey32_data(self):
        """
        Voer twee authentisatiepogingen (via target mode) uit op een bepaald block (bijv. block 3)
        en retourneer een dictionary met de benodigde data (uid, nt, nr0, ar0, nt1, nr1, ar1)
        voor de mfkey32-aanval.
        """
        uid = self.current_card_uid
        if uid is None:
            print("Geen kaart UID beschikbaar.")
            return None

        DEFAULT_KEY_A = b'\xFF\xFF\xFF\xFF\xFF\xFF'
        block_number = 3  # Pas aan indien nodig

        # Probeer eerst één authentisatiepoging (bijvoorbeeld met target mode)
        print("Eerste authenticatiepoging (target mode)...")
        auth1 = self.capture_auth_data(block_number)
        print("Tweede authenticatiepoging (target mode)...")
        auth2 = self.capture_auth_data(block_number)

        if auth1 is None or auth2 is None:
            print("Authenticatie mislukt voor een of beide pogingen.")
            return None

        try:
            nt0 = auth1[0:4]
            nr0 = auth1[4:8]
            ar0 = auth1[8:12]
            nt1 = auth2[0:4]
            nr1 = auth2[4:8]
            ar1 = auth2[8:12]
        except Exception as e:
            print("Fout bij verwerken authenticatie-respons:", e)
            return None

        data = {
            "uid": "".join("{:02X}".format(b) for b in uid),
            "nt": "".join("{:02X}".format(b) for b in nt0),
            "nr0": "".join("{:02X}".format(b) for b in nr0),
            "ar0": "".join("{:02X}".format(b) for b in ar0),
            "nt1": "".join("{:02X}".format(b) for b in nt1),
            "nr1": "".join("{:02X}".format(b) for b in nr1),
            "ar1": "".join("{:02X}".format(b) for b in ar1)
        }
        print("Verzamelde mfkey32-data:")
        for key, val in data.items():
            print(f"  {key}: {val}")
        return data

    def run_mfkey32(self):
        print("RUNNING MFKEY32 with cached data:")
        print(self.cached_card_data)
        if self.cached_card_data is None:
            return "Geen kaartdata beschikbaar voor mfkey32."
        # Dummy resultaat; in een echte implementatie voer je de mfkey32-aanval uit met self.cached_card_data
        result = {"key_a": "A0A1A2A3A4A5", "key_b": "B0B1B2B3B4B5"}
        return result

    def clear_cached_data(self):
        self.cached_card_data = None
