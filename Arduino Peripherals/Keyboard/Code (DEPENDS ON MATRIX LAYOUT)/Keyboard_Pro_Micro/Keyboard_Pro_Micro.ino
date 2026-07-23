/**
 * @file Keyboard_Pro_Micro_5x4.ino
 * @brief DSKY Keyboard Matrix Controller (5x4 Variant)
 *
 * Scans a 5x4 physical button matrix and transmits key presses and releases
 * via serial to the host device. Includes WHOAMI handshake response for port identification.
 */
#include <Keypad.h>

// --- Hardware Configuration ---
constexpr uint8_t MATRIX_ROWS = 5;
constexpr uint8_t MATRIX_COLS = 4;

// Physical pin assignments
constexpr uint8_t ROW_PINS[MATRIX_ROWS] = {6, 5, 4, 3, 2};
constexpr uint8_t COL_PINS[MATRIX_COLS] = {10, 9, 8, 7};

// --- Keymap Definition ---
char KEY_MAP[MATRIX_ROWS][MATRIX_COLS] = {
  {'C', 'P', 'K', 'E'},
  {'9', '6', '3', 'R'},
  {'8', '5', '2', 'E'}, 
  {'7', '4', '1', 'N'},
  {'+', '-', '0', 'V'}
};

Keypad dsky_keypad = Keypad(makeKeymap(KEY_MAP), ROW_PINS, COL_PINS, MATRIX_ROWS, MATRIX_COLS);

// --- Function Prototypes ---
void handle_handshake();
void keypad_event(KeypadEvent key);

void setup() {
  Serial.begin(115200);
  dsky_keypad.addEventListener(keypad_event);
}

void loop() {
  // Advance the keypad state machine
  dsky_keypad.getKey();
  handle_handshake();
}

/**
 * @brief Intercepts 'W' (WHOAMI) queries and responds with the device identifier.
 */
void handle_handshake() {
  if (Serial.available() > 0 && (Serial.peek() == 'W' || Serial.peek() == 'w')) {
    // Flush the receive buffer
    while (Serial.available() > 0) {
        Serial.read();
    }
    Serial.println("DSKY_KEYBOARD");
  }
}

/**
 * @brief Callback triggered on physical key state change.
 * @param key The character corresponding to the physical matrix intersection.
 */
void keypad_event(KeypadEvent key) {
  switch (dsky_keypad.getState()) {
    case PRESSED:
      Serial.print(key);
      Serial.println("_D"); 
      break;
    case RELEASED:
      Serial.print(key);
      Serial.println("_U");
      break;
    case HOLD:
    case IDLE:
      // Explicitly unhandled states for compliance
      break;
  }
}