#!/usr/bin/env python3
"""
safe_shutdown.py

Hardware monitor for the soft-latch power management circuit.
Maintains active-high state on the main relay and monitors a discrete input 
pin for a manual hardware shutdown interrupt. Initiates a safe OS halt before 
dropping relay power.
"""

import os
import time
import logging
import RPi.GPIO as GPIO

# --- Hardware Configuration ---
RELAY_PIN: int = 17     # BCM numbering: Main power latch relay
SHUTDOWN_PIN: int = 27  # BCM numbering: Momentary shutdown trigger

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def initialize_gpio() -> None:
    """Configures the Broadcom GPIO pin states for the power latch circuit."""
    GPIO.setmode(GPIO.BCM)
    
    # Energize relay to maintain system power
    GPIO.setup(RELAY_PIN, GPIO.OUT, initial=GPIO.HIGH)
    
    # Configure momentary switch input with internal pull-up resistor
    GPIO.setup(SHUTDOWN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    logging.info("GPIO initialized. Relay latched HIGH. Awaiting interrupt on PIN %d.", SHUTDOWN_PIN)

def monitor_shutdown_interrupt() -> None:
    """
    Continuously polls the shutdown pin. Triggers a system halt when pulled LOW.
    Executes at a 2Hz polling rate to minimize CPU overhead.
    """
    logging.info("Hardware shutdown monitor active.")
    try:
        while True:
            # Listen for manual shutdown trigger
            if GPIO.input(SHUTDOWN_PIN) == GPIO.LOW:
                logging.warning("Hardware interrupt detected. Initiating safe system poweroff.")
                os.system("poweroff")
                
                # Park execution to maintain GPIO states during the OS halt sequence.
                # The kernel will forcefully terminate this process before dropping the 3.3V rail.
                time.sleep(10)
            
            time.sleep(0.5)

    except KeyboardInterrupt:
        logging.info("Shutdown monitor terminated via keyboard interrupt.")

    finally:
        logging.info("Cleaning up GPIO resources.")
        GPIO.cleanup()

def main() -> None:
    """Main execution sequence."""
    try:
        initialize_gpio()
        monitor_shutdown_interrupt()
    except Exception as e:
        logging.error("Fatal error in shutdown monitor: %s", e)
        GPIO.cleanup()

if __name__ == "__main__":
    main()