#!/usr/bin/env python3
"""
MyDSKYTunnel.py

DirectInput bridge and autonomous lifecycle manager for Apollo DSKY hardware.
Receives UDP telemetry and translates it into hardware-level keystrokes.
Self-terminates upon detecting the closure of the host simulator process.
"""

import ctypes
import socket
import time
import logging
import threading
import subprocess
import os

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)

# --- DirectInput Constants & Types ---
DIK_LSHIFT = 0x2A
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001

PUL = ctypes.POINTER(ctypes.c_ulong)

class KeyBdInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", PUL)]

class HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong),
                ("wParamL", ctypes.c_short),
                ("wParamH", ctypes.c_ushort)]

class MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", PUL)]

class Input_I(ctypes.Union):
    _fields_ = [("ki", KeyBdInput),
                ("mi", MouseInput),
                ("hi", HardwareInput)]

class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong),
                ("ii", Input_I)]

# --- Hardware Mapping ---
DSKY_KEY_MAPPING = {
    "VERB":   (0x35, True),
    "NOUN":   (0x37, False),
    "PLUS":   (0x4E, False),
    "MINUS":  (0x4A, False),
    "CLR":    (0x53, False),
    "ENTR":   (0x1C, True),
    "PRO":    (0x4F, True),
    "KEYREL": (0x47, True),
    "RSET":   (0x49, True),
    "0":      (0x52, False),
    "1":      (0x4F, False),
    "2":      (0x50, False),
    "3":      (0x51, False),
    "4":      (0x4B, False),
    "5":      (0x4C, False),
    "6":      (0x4D, False),
    "7":      (0x47, False),
    "8":      (0x48, False),
    "9":      (0x49, False)
}

class OrbiterInputBridge:
    """Manages stateful DirectInput transmission to the host simulator."""
    
    def __init__(self):
        self.active_keys = set()
        self.send_input = ctypes.windll.user32.SendInput

    def _transmit_keystroke(self, hex_key_code: int, is_extended: bool, key_up: bool) -> None:
        """Constructs and dispatches the native C-struct to the Windows input buffer."""
        extra = ctypes.c_ulong(0)
        flags = KEYEVENTF_SCANCODE
        
        if is_extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        if key_up:
            flags |= KEYEVENTF_KEYUP

        ii_ = Input_I()
        ii_.ki = KeyBdInput(0, hex_key_code, flags, 0, ctypes.pointer(extra))
        command = Input(ctypes.c_ulong(1), ii_)
        
        self.send_input(1, ctypes.pointer(command), ctypes.sizeof(command))

    def process_network_event(self, network_msg: str) -> None:
        """Parses incoming UDP payload and coordinates physical input state."""
        if "_" not in network_msg:
            return
            
        key_label, state = network_msg.split("_", 1)
        if key_label not in DSKY_KEY_MAPPING:
            return
            
        scan_code, is_ext = DSKY_KEY_MAPPING[key_label]
        
        if state == "D":
            if not self.active_keys:
                self._transmit_keystroke(DIK_LSHIFT, False, False)
                time.sleep(0.05)
                
            self.active_keys.add(key_label)
            self._transmit_keystroke(scan_code, is_ext, False)
            
        elif state == "U":
            self._transmit_keystroke(scan_code, is_ext, True)
            self.active_keys.discard(key_label)
            
            if not self.active_keys:
                time.sleep(0.05)
                self._transmit_keystroke(DIK_LSHIFT, False, True)

def orbiter_watchdog() -> None:
    """
    Monitors the Windows process list and self-terminates the script when Orbiter closes.
    Runs in an isolated daemon thread to prevent main loop blocking.
    """
    orbiter_was_running = False
    CREATE_NO_WINDOW = 0x08000000 
    
    while True:
        try:
            output = subprocess.check_output(
                'tasklist /FI "IMAGENAME eq orbiter.exe"', 
                shell=False, 
                creationflags=CREATE_NO_WINDOW
            ).decode()
            is_running = "orbiter.exe" in output.lower()
        except Exception:
            is_running = False

        if is_running:
            orbiter_was_running = True
        elif orbiter_was_running and not is_running:
            logging.info("Host simulator process terminated. Initiating shutdown.")
            os._exit(0)
            
        time.sleep(5)

def main() -> None:
    udp_ip = "0.0.0.0"
    udp_port = 3003

    watchdog_thread = threading.Thread(target=orbiter_watchdog, daemon=True)
    watchdog_thread.start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((udp_ip, udp_port))
    
    bridge = OrbiterInputBridge()
    
    logging.info("--- NASSP DSKY Hardware Receiver Active ---")
    logging.info("Listening for UDP datagrams on port %d...", udp_port)

    try:
        while True:
            data, addr = sock.recvfrom(1024)
            msg = data.decode("ascii").strip()
            logging.info("[%s] -> %s", addr[0], msg)
            bridge.process_network_event(msg)
    except KeyboardInterrupt:
        logging.info("Hardware receiver terminated.")

if __name__ == '__main__':
    main()