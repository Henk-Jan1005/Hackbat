import time
import json
from machine import I2C, Pin
from i2c import PN532_I2C
from display import Display, debug_print

class NFCModule:
    def __init__(self):
        self.i2c = I2C(0, scl=Pin(5), sda=Pin(4))
        self.pn532 = PN532_I2C(self.i2c, debug=True)
        self.pn532.SAM_configuration()
        # Huidige kaartgegevens
        self.current_card_uid = None
        self.current_card_atqa = None
        self.current_card_sak = None
        self.current_card_info = None
        self.current_card_type = None

    def read_full_card(self):
        """Leest de volledige kaart uit (MIFARE Classic 1K): UID, sector data, trailer."""
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
            cracked_data = json.dumps(card_dump)
            Display.update_status("Kaartdata voor mfkey32 verzonden!")
            print("Kaartdata voor mfkey32:", cracked_data)
            return cracked_data
        else:
            Display.update_status("Capture failed!")
            return None

    def run_mfkey32(self):
        """
        Voert (dummy) mfkey32-aanval uit op de huidige kaartdata.
        In een echte implementatie komt hier de brute force- of nested attack.
        """
        card_dump = self.read_full_card()
        if card_dump is None:
            return "Geen kaartdata beschikbaar voor mfkey32."
        # Dummy resultaat: voorbeeldsleutels
        result = {"key_a": "A0A1A2A3A4A5", "key_b": "B0B1B2B3B4B5"}
        return json.dumps(result, indent=2)

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
        """Detecteert een kaart en werkt de globale kaartgegevens bij.
           De parameter menu_active zorgt ervoor dat tijdens een menu-actieve status
           er geen nieuwe kaart wordt ingelezen."""
        try:
            if not self.pn532.listen_for_passive_target(timeout=500) or menu_active:
                return
            COMMAND_INLISTPASSIVETARGET = 0x4A
            response = self.pn532.process_response(COMMAND_INLISTPASSIVETARGET, response_length=30, timeout=500)
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
            Display.update_status(self.current_card_info)
            print("Found card with UID:", uid_str, "ATQA:", atqa_str, "Type:", self.current_card_type)
        except Exception as e:
            debug_print("Error reading card: " + str(e))
