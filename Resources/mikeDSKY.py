#!/usr/bin/env python3
"""
mikeDSKY.py

Universal Routing Hub for Custom Apollo DSKY Hardware.
Provides seamless hardware-level switching between yaAGC (Local) and NASSP (PC).
"""

import argparse
import socket
import select
import json
import time
import re
import serial
import serial.tools.list_ports
import sys
import logging
from typing import Optional, Tuple, Dict, Any

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)

# Constants & Key Mappings
MASTER_KEY_MAP = {
    'V': 'VERB', 'N': 'NOUN', '+': 'PLUS', '-': 'MINUS',
    'C': 'CLR',  'E': 'ENTR', 'P': 'PRO',  'K': 'KEYREL',
    'R': 'RSET', '0': '0', '1': '1', '2': '2', '3': '3',
    '4': '4', '5': '5', '6': '6', '7': '7', '8': '8', '9': '9'
}

AGC_KEY_CODES = {
    '0': 0o20, '1': 0o1, '2': 0o2, '3': 0o3, '4': 0o4, 
    '5': 0o5, '6': 0o6, '7': 0o7, '8': 0o10, '9': 0o11,
    '+': 0o32, '-': 0o33, 'V': 0o21, 'N': 0o37, 'R': 0o22, 
    'C': 0o36, 'K': 0o31, 'E': 0o34
}

def find_arduino(identity: str, name: str) -> Optional[serial.Serial]:
    """Scans active USB/ACM ports for a specific Arduino handshake identifier."""
    logging.info("Scanning USB ports for %s...", name)
    for p in serial.tools.list_ports.comports():
        if "ACM" in p.device or "USB" in p.device: 
            try:
                ser = serial.Serial(p.device, 115200, timeout=1.0)
                ser.reset_input_buffer()
                ser.write(b"WHOAMI\n")
                reply = ser.readline().decode('ascii', errors='ignore').strip()
                if identity in reply:
                    logging.info("Success: %s found on %s", name, p.device)
                    return ser
                ser.close()
            except serial.SerialException:
                pass
    return None

class DSKYRouter:
    """Main application class managing state, routing, and hardware abstraction."""
    
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.current_mode = "YAAGC"
        
        # Hardware setup
        self.panel_ser = find_arduino("DSKY_DISPLAY", "Display")
        if not self.panel_ser:
            sys.exit("CRITICAL ERROR: Display Arduino not found!")
            
        self.kbd_ser = find_arduino("DSKY_KEYBOARD", "Keyboard")
        
        # Network setup
        self.nassp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.nassp_sock.bind(("", self.args.json_port))

        self.key_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.key_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self.agc_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.agc_sock.setblocking(False)
        
        logging.info("Attempting connection to yaAGC (%s:%d)...", self.args.agc_host, self.args.agc_port)
        try:
            self.agc_sock.connect((self.args.agc_host, self.args.agc_port))
        except BlockingIOError:
            pass

        # Frame State
        self.last_nassp_frame = bytearray(b'0' * 38)
        self.last_agc_frame = bytearray(b'0' * 38)
        
        # Hardware interrupt timing
        self.reset_down_time = 0.0
        self.reset_is_active = False

        # yaAGC State Variables
        self.lamp_statuses = {k: {"isLit": False} for k in [
            "UPLINK ACTY", "TEMP", "NO ATT", "GIMBAL LOCK", "DSKY STANDBY", "PROG",
            "KEY REL", "RESTART", "OPR ERR", "TRACKER", "PRIO DSP", "ALT",
            "NO DAP", "VEL", "COMP ACTY"
        ]}
        self.verb = [" ", " "]
        self.noun = [" ", " "]
        self.prog = [" ", " "]
        self.regs_agc = [" "] * 18
        self.plus_minus = [0, 0, 0]
        self.agc_vn_flash = False
        
        # Flasher state
        self.flash_state = True
        self.last_flash = time.time()

    def toggle_mode(self) -> None:
        """Toggles active network route between local yaAGC and remote NASSP."""
        if self.current_mode == "NASSP":
            self.current_mode = "YAAGC"
            logging.info("=== SWITCHED MODE TO: yaAGC (LOCAL) ===")
            self.panel_ser.write(self.last_agc_frame) 
        else:
            self.current_mode = "NASSP"
            logging.info("=== SWITCHED MODE TO: NASSP (PC) ===")
            self.panel_ser.write(self.last_nassp_frame) 

    # yaAGC Logic
    def packetize_agc(self, tup: Tuple[int, int, int]) -> None:
        """Encodes keystrokes into the strictly formatted 4-byte yaAGC structure."""
        out = bytearray(4)
        out[0] = 0x20 | ((tup[0] >> 3) & 0x0F)
        out[1] = 0x40 | ((tup[0] << 3) & 0x38) | ((tup[2] >> 12) & 0x07)
        out[2] = 0x80 | ((tup[2] >> 6) & 0x3F)
        out[3] = 0xC0 | (tup[2] & 0x3F)
        try: 
            self.agc_sock.sendall(out)
        except Exception: 
            pass
        
        out[0] = 0x00 | ((tup[0] >> 3) & 0x0F)
        out[1] = 0x40 | ((tup[0] << 3) & 0x38) | ((tup[1] >> 12) & 0x07)
        out[2] = 0x80 | ((tup[1] >> 6) & 0x3F)
        out[3] = 0xC0 | (tup[1] & 0x3F)
        try: 
            self.agc_sock.sendall(out)
        except Exception: 
            pass

    def send_to_agc(self, char: str, state: str) -> None:
        """Handles physical key state mapping to yaAGC simulator codes."""
        data = []
        if state == 'D':
            if char == 'P': 
                data.append((0o32, 0o00000, 0o20000))
            elif char in AGC_KEY_CODES: 
                data.append((0o15, AGC_KEY_CODES[char], 0o37))
        elif state == 'U':
            # PRO physical switch requires up-state signal
            if char == 'P': 
                data.append((0o32, 0o20000, 0o20000))
                
        for d in data: 
            self.packetize_agc(d)

    def decode_agc_char(self, code: int) -> str:
        """Translates octal AGC character codes to standard strings."""
        return {
            0:" ", 21:"0", 3:"1", 25:"2", 27:"3", 15:"4", 
            30:"5", 28:"6", 19:"7", 29:"8", 31:"9"
        }.get(code, "?")

    def process_agc_output(self, channel: int, value: int) -> None:
        """Parses bitmasked channel data from yaAGC into discrete register updates."""
        if channel == 0o13: 
            value &= 0o3000
            
        if channel == 0o10:
            a = (value >> 11) & 0x0F
            b = (value >> 10) & 0x01
            sc = self.decode_agc_char((value >> 5) & 0x1F)
            sd = self.decode_agc_char(value & 0x1F)
            
            if a == 11: self.prog[0], self.prog[1] = sc, sd
            elif a == 10: self.verb[0], self.verb[1] = sc, sd
            elif a == 9: self.noun[0], self.noun[1] = sc, sd
            elif a == 8: self.regs_agc[1] = sd
            elif a in (7, 5, 2): 
                idx = {7:0, 5:1, 2:2}[a]
                self.plus_minus[idx] = (self.plus_minus[idx] | 1) if b else (self.plus_minus[idx] & ~1)
                char = "+" if self.plus_minus[idx] == 1 else ("-" if self.plus_minus[idx] == 2 else " ")
                
                if a == 7: self.regs_agc[0], self.regs_agc[2], self.regs_agc[3] = char, sc, sd
                elif a == 5: self.regs_agc[6], self.regs_agc[7], self.regs_agc[8] = char, sc, sd
                elif a == 2: self.regs_agc[12], self.regs_agc[14], self.regs_agc[15] = char, sc, sd
            elif a == 6: self.regs_agc[4], self.regs_agc[5] = sc, sd
            elif a == 4: self.regs_agc[9], self.regs_agc[10] = sc, sd
            elif a == 3: self.regs_agc[11], self.regs_agc[13] = sc, sd
            elif a == 1: self.regs_agc[16], self.regs_agc[17] = sc, sd
            elif a == 12:
                flags = [
                    ("VEL", 0x04), ("NO ATT", 0x08), ("ALT", 0x10), 
                    ("GIMBAL LOCK", 0x20), ("TRACKER", 0x80), ("PROG", 0x100)
                ]
                for n, m in flags:
                    self.lamp_statuses[n]["isLit"] = (value & m) != 0
                    
        elif channel == 0o11:
            self.lamp_statuses["COMP ACTY"]["isLit"] = (value & 0x02) != 0
            self.lamp_statuses["UPLINK ACTY"]["isLit"] = (value & 0x04) != 0
            self.agc_vn_flash = (value & 0x20) != 0
            
        elif channel == 0o163:
            flags = [
                ("TEMP", 0x08), ("KEY REL", 0o20), ("OPR ERR", 0o100), 
                ("RESTART", 0o200), ("DSKY STANDBY", 0o400)
            ]
            for n, m in flags:
                self.lamp_statuses[n]["isLit"] = (value & m) != 0

    def update_agc_lamps(self) -> None:
        """Constructs and transmits the 38-byte hardware payload for local AGC."""
        tosend = bytearray(b'0' * 38)
        lamps = ['UPLINK ACTY', 'NO ATT', 'DSKY STANDBY', 'KEY REL', 'OPR ERR', 
                 'TEMP', 'GIMBAL LOCK', 'PROG', 'RESTART', 'TRACKER']
                 
        for i, l in enumerate(lamps): 
            tosend[i] = ord('1') if self.lamp_statuses[l]["isLit"] else ord('0')
            
        tosend[13] = ord('1') if self.lamp_statuses['COMP ACTY']["isLit"] else ord('0')
        tosend[14], tosend[15] = ord(self.prog[0]), ord(self.prog[1])
        
        show_vn = self.flash_state or not self.agc_vn_flash
        tosend[16] = ord(self.verb[0]) if show_vn else ord(' ')
        tosend[17] = ord(self.verb[1]) if show_vn else ord(' ')
        tosend[18] = ord(self.noun[0]) if show_vn else ord(' ')
        tosend[19] = ord(self.noun[1]) if show_vn else ord(' ')
        
        for i, val in enumerate(self.regs_agc): 
            tosend[20 + i] = ord(val)

        if tosend != self.last_agc_frame:
            self.last_agc_frame = tosend
            if self.current_mode == "YAAGC": 
                self.panel_ser.write(tosend)

    # NASSP Logic
    @staticmethod
    def format_nassp_pair(raw_val: Any) -> str:
        """
        Formats 2-digit displays left-to-right (e.g., '3' -> '3 ', '35' -> '35').
        """
        val = str(raw_val).strip()
        if not val:
            return "  "
        return val.ljust(2, " ")[:2]

    def process_nassp_json(self, state: Dict[str, Any]) -> None:
        """Parses telemetry payload from NASSP over UDP into hardware string."""
        alarms = str(state.get("alarms", ""))
        bits = re.findall(r"[01]", alarms)
        if len(bits) < 10: 
            bits += ["0"] * (10 - len(bits))
        
        prog = self.format_nassp_pair(state.get("prog", ""))
        verb = self.format_nassp_pair(state.get("verb", ""))
        noun = self.format_nassp_pair(state.get("noun", ""))
        
        fmask = 0
        try: 
            fmask = int(str(state.get("flashing", 0)).strip())
        except ValueError: 
            pass

        if not self.flash_state:
            if fmask & 0x1: verb, noun = "  ", "  "
            if fmask & 0x2: prog = "  "

        comp_val = 0
        try: 
            comp_val = int(str(state.get("compLight", 0)).strip())
        except ValueError: 
            pass

        buf = ["0"] * 38
        for i in range(10): 
            buf[i] = "1" if bits[i] == "1" else "0"
            
        buf[13] = "1" if comp_val else "0"
        buf[14], buf[15] = prog[0], prog[1]
        buf[16], buf[17] = verb[0], verb[1]
        buf[18], buf[19] = noun[0], noun[1]

        for idx, key in enumerate(("r1", "r2", "r3")):
            raw = str(state.get(key, "")).strip()
            base = 20 + idx * 6
            if not raw:
                for j in range(6): 
                    buf[base + j] = " "
            else:
                sign = raw[0] if raw[0] in "+-" else " "
                mag = "".join(filter(str.isdigit, raw)).rjust(5, "0")[-5:]
                reg = sign + mag
                for j, ch in enumerate(reg): 
                    buf[base + j] = ch

        frame = "".join(buf).encode("ascii")
        if frame != self.last_nassp_frame:
            self.last_nassp_frame = frame
            if self.current_mode == "NASSP": 
                self.panel_ser.write(frame)

    def run(self) -> None:
        """Main execution loop containing multiplexed socket draining and serial parsing."""
        logging.info("--- DSKY MASTER ROUTER ACTIVE ---")
        logging.info("Current Mode: %s", self.current_mode)

        agc_buf = bytearray(4)
        agc_view = memoryview(agc_buf)
        agc_left = 4

        while True:
            now = time.time()
            
            # Hardware Interrupt for Mode Swapping
            if self.reset_is_active and (now - self.reset_down_time >= 4.0):
                if self.current_mode == 'NASSP':
                    self.key_sock.sendto(
                        f"{MASTER_KEY_MAP['R']}_U".encode("ascii"), 
                        (self.args.key_host, self.args.key_port)
                    )
                self.reset_is_active = False 
                self.toggle_mode()

            # Global Flasher Clock
            if now - self.last_flash >= 0.6:
                self.flash_state = not self.flash_state
                self.last_flash = now
                self.update_agc_lamps() 

            ready, _, _ = select.select([self.nassp_sock, self.agc_sock, self.kbd_ser], [], [], 0.05)
            
            for src in ready:
                if src is self.nassp_sock:
                    data, _ = self.nassp_sock.recvfrom(4096)
                    try: 
                        self.process_nassp_json(json.loads(data.decode("utf-8")))
                    except json.JSONDecodeError: 
                        pass

                elif src is self.agc_sock:
                    did_agc_update = False
                    
                    # Instantaneous Drain Loop: 
                    # Absorbs yaAGC packets back-to-back before writing to Arduino
                    while True:
                        try:
                            num = self.agc_sock.recv_into(agc_view, agc_left)
                            if num > 0:
                                agc_view = agc_view[num:]
                                agc_left -= num
                                if agc_left == 0:
                                    ch = (agc_buf[0] & 0x0F) << 3 | (agc_buf[1] & 0x38) >> 3
                                    val = (agc_buf[1] & 0x07) << 12 | (agc_buf[2] & 0x3F) << 6 | (agc_buf[3] & 0x3F)
                                    self.process_agc_output(ch, val)
                                    did_agc_update = True
                                    
                                    # Reset buffer view for next 4-byte packet
                                    agc_view = memoryview(agc_buf)
                                    agc_left = 4
                            else:
                                break
                        except (BlockingIOError, ConnectionResetError):
                            break
                    
                    # Push final hardware layout only after buffer is drained
                    if did_agc_update:
                        self.update_agc_lamps()

                elif src is self.kbd_ser:
                    while self.kbd_ser.in_waiting > 0:
                        line = self.kbd_ser.readline().decode("ascii", "ignore").strip().upper()
                        if not line or '_' not in line: 
                            continue
                            
                        char, state = line.split('_', 1)

                        if char == 'R':
                            if state == 'D':
                                self.reset_down_time = time.time()
                                self.reset_is_active = True
                            elif state == 'U':
                                self.reset_is_active = False

                        if self.current_mode == 'NASSP':
                            label = MASTER_KEY_MAP.get(char, char)
                            out_msg = f"{label}_{state}"
                            self.key_sock.sendto(out_msg.encode("ascii"), (self.args.key_host, self.args.key_port))
                            
                        elif self.current_mode == 'YAAGC':
                            self.send_to_agc(char, state)


if __name__ == "__main__":
    cli_parser = argparse.ArgumentParser(description="Master Router for yaAGC and NASSP")
    cli_parser.add_argument("--json-port", type=int, default=3002, help="UDP port for NASSP JSON")
    cli_parser.add_argument("--key-host", default="255.255.255.255", help="Broadcast for NASSP PC")
    cli_parser.add_argument("--key-port", type=int, default=3003, help="Port for NASSP PC")
    cli_parser.add_argument("--agc-host", default="localhost", help="Host address of yaAGC")
    cli_parser.add_argument("--agc-port", type=int, default=19697, help="Port for yaAGC")
    
    parsed_args = cli_parser.parse_args()
    
    router = DSKYRouter(parsed_args)
    try:
        router.run()
    except KeyboardInterrupt:
        logging.info("DSKY Router terminated by user.")
        sys.exit(0)