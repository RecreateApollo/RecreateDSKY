/**
 * @file Nextion_LED_Pro_Micro.ino
 * @brief DSKY Display and Annunciator Controller
 *
 * Receives telemetry payloads from the host system to drive 10 hardware LEDs
 * and a Nextion serial display. Memory allocation is strictly static.
 */
#include <Arduino.h>

// --- Hardware Configuration ---
#define NEXTION_SERIAL Serial1 // Hardware Serial 1 (D0=RX, D1=TX)

// LED Pin Assignments
constexpr uint8_t PIN_UPLINK   = 9;
constexpr uint8_t PIN_ATT      = 8;
constexpr uint8_t PIN_STBY     = 10;
constexpr uint8_t PIN_KEY      = 16;
constexpr uint8_t PIN_ERR      = 14;
constexpr uint8_t PIN_TEMP     = 15;
constexpr uint8_t PIN_GIMBAL   = A0;
constexpr uint8_t PIN_PROG     = A1;
constexpr uint8_t PIN_RESTART  = A2;
constexpr uint8_t PIN_TRACKER  = A3;

constexpr uint8_t LED_PINS[] = {
    PIN_UPLINK, PIN_ATT, PIN_STBY, PIN_KEY, PIN_ERR,
    PIN_TEMP, PIN_GIMBAL, PIN_PROG, PIN_RESTART, PIN_TRACKER
};
constexpr uint8_t NUM_LEDS = sizeof(LED_PINS) / sizeof(LED_PINS[0]);

// --- Communication Constants ---
constexpr size_t PAYLOAD_SIZE = 38;
constexpr size_t BUFFER_SIZE = 40;

// --- Global State ---
char rx_buffer[BUFFER_SIZE];
bool payload_ready = false;

// --- Function Prototypes ---
void initialize_hardware();
void process_serial_input();
void handle_handshake_and_test();
void execute_self_test();
void update_led_states();
void update_display_states();
void send_nextion_cmd(const char* cmd);
void set_nextion_text(const char* component, char value);
char sanitize_display_char(char input);

void setup() {
    initialize_hardware();
}

void loop() {
    handle_handshake_and_test();
    process_serial_input();

    if (payload_ready) {
        update_led_states();
        update_display_states();
        payload_ready = false;
    }
}

/**
 * @brief Configures serial buses and verifies LED array continuity.
 */
void initialize_hardware() {
    // Initialize LED array
    for (uint8_t i = 0; i < NUM_LEDS; i++) {
        pinMode(LED_PINS[i], OUTPUT);
        digitalWrite(LED_PINS[i], HIGH);
    }
    delay(500); 
    for (uint8_t i = 0; i < NUM_LEDS; i++) {
        digitalWrite(LED_PINS[i], LOW);
    }

    // Initialize Serial Interfaces
    Serial.begin(115200);       // USB Data Bus
    NEXTION_SERIAL.begin(9600); // Nextion TX/RX Bus

    send_nextion_cmd("comp_acty.pic=2");
    Serial.println("DSKY Display Controller Ready. Type 't' for self-test.");
}

/**
 * @brief Polls incoming serial commands for diagnostic triggers or handshaking.
 */
void handle_handshake_and_test() {
    if (Serial.available() > 0) {
        char peek_char = Serial.peek();

        // Hardware Self-Test
        if (peek_char == 't' || peek_char == 'T') {
            Serial.read(); // Consume trigger
            execute_self_test();
        }
        // WHOAMI Handshake Routine
        else if (peek_char == 'W' || peek_char == 'w') {
            while (Serial.available() > 0) {
                Serial.read(); // Flush buffer
            }
            Serial.println("DSKY_DISPLAY");
        }
    }
}

/**
 * @brief Extracts fixed-size data payload from the serial buffer.
 */
void process_serial_input() {
    if (Serial.available() >= PAYLOAD_SIZE) {
        Serial.readBytes(rx_buffer, PAYLOAD_SIZE);
        payload_ready = true;

        // Flush trailing data to prevent frame desynchronization
        while (Serial.available() > 0) {
            Serial.read();
        }
    }
}

/**
 * @brief Maps active buffer indices directly to physical LED pin states.
 */
void update_led_states() {
    digitalWrite(PIN_UPLINK,  rx_buffer[0] - '0');
    digitalWrite(PIN_ATT,     rx_buffer[1] - '0');
    digitalWrite(PIN_STBY,    rx_buffer[2] - '0');
    digitalWrite(PIN_KEY,     rx_buffer[3] - '0');
    digitalWrite(PIN_ERR,     rx_buffer[4] - '0');
    digitalWrite(PIN_TEMP,    rx_buffer[5] - '0');
    digitalWrite(PIN_GIMBAL,  rx_buffer[6] - '0');
    digitalWrite(PIN_PROG,    rx_buffer[7] - '0');
    digitalWrite(PIN_RESTART, rx_buffer[8] - '0');
    digitalWrite(PIN_TRACKER, rx_buffer[9] - '0');
}

/**
 * @brief Converts specialized AGC numerical characters to displayable ASCII.
 * @param input Raw character byte from the AGC payload.
 * @return Sanitized ASCII character.
 */
char sanitize_display_char(char input) {
    if (input == 32) return ' ';
    if (input == 43) return '+';
    if (input == 45) return '-';
    return input;
}

/**
 * @brief Parses payload and issues updates to Nextion UI components if values have changed.
 */
void update_display_states() {
    char prog[2] = { sanitize_display_char(rx_buffer[14]), sanitize_display_char(rx_buffer[15]) };
    char verb[2] = { sanitize_display_char(rx_buffer[16]), sanitize_display_char(rx_buffer[17]) };
    char noun[2] = { sanitize_display_char(rx_buffer[18]), sanitize_display_char(rx_buffer[19]) };

    char r1[6], r2[6], r3[6];
    for (uint8_t i = 0; i < 6; i++) {
        r1[i] = sanitize_display_char(rx_buffer[20 + i]);
        r2[i] = sanitize_display_char(rx_buffer[26 + i]);
        r3[i] = sanitize_display_char(rx_buffer[32 + i]);
    }

    // Static memory caching to drastically reduce serial TX volume
    static char old_prog[2] = {0};
    static char old_verb[2] = {0};
    static char old_noun[2] = {0};
    static char old_r1[6]   = {0};
    static char old_r2[6]   = {0};
    static char old_r3[6]   = {0};
    static int  old_comp_acty = -1;

    // Component Updates
    if (prog[0] != old_prog[0]) { set_nextion_text("PROG1", prog[0]); old_prog[0] = prog[0]; }
    if (prog[1] != old_prog[1]) { set_nextion_text("PROG2", prog[1]); old_prog[1] = prog[1]; }
    if (verb[0] != old_verb[0]) { set_nextion_text("VERB1", verb[0]); old_verb[0] = verb[0]; }
    if (verb[1] != old_verb[1]) { set_nextion_text("VERB2", verb[1]); old_verb[1] = verb[1]; }
    if (noun[0] != old_noun[0]) { set_nextion_text("NOUN1", noun[0]); old_noun[0] = noun[0]; }
    if (noun[1] != old_noun[1]) { set_nextion_text("NOUN2", noun[1]); old_noun[1] = noun[1]; }

    // Register Array Updates
    char id_buffer[10];
    for (uint8_t i = 0; i < 6; i++) {
        if (r1[i] != old_r1[i]) {
            snprintf(id_buffer, sizeof(id_buffer), "R1_%d", i + 1);
            set_nextion_text(id_buffer, r1[i]);
            old_r1[i] = r1[i];
        }
        if (r2[i] != old_r2[i]) {
            snprintf(id_buffer, sizeof(id_buffer), "R2_%d", i + 1);
            set_nextion_text(id_buffer, r2[i]);
            old_r2[i] = r2[i];
        }
        if (r3[i] != old_r3[i]) {
            snprintf(id_buffer, sizeof(id_buffer), "R3_%d", i + 1);
            set_nextion_text(id_buffer, r3[i]);
            old_r3[i] = r3[i];
        }
    }

    // COMP ACTY Status Light
    int comp_acty = rx_buffer[13] - '0';
    if (comp_acty != old_comp_acty) {
        send_nextion_cmd(comp_acty ? "comp_acty.pic=3" : "comp_acty.pic=2");
        old_comp_acty = comp_acty;
    }
}

/**
 * @brief Transmits raw command string to Nextion display with required termination.
 * @param cmd C-string command payload.
 */
void send_nextion_cmd(const char* cmd) {
    NEXTION_SERIAL.print(cmd);
    NEXTION_SERIAL.write(0xFF);
    NEXTION_SERIAL.write(0xFF);
    NEXTION_SERIAL.write(0xFF);
    delay(10); // Enforce pacing required for Nextion instruction execution
}

/**
 * @brief Updates a targeted text element on the Nextion display.
 * @param component The UI component ID (e.g., "R1_1").
 * @param value The character to output.
 */
void set_nextion_text(const char* component, char value) {
    char buffer[32];
    snprintf(buffer, sizeof(buffer), "%s.txt=\"%c\"", component, value);
    send_nextion_cmd(buffer);
}

/**
 * @brief Executes full hardware diagnostic routine for LEDs and Display segments.
 */
void execute_self_test() {
    Serial.println("Executing hardware self-test...");

    // 1. Annunciator Sequence
    for (uint8_t i = 0; i < NUM_LEDS; i++) {
        digitalWrite(LED_PINS[i], HIGH);
        delay(200);
        digitalWrite(LED_PINS[i], LOW);
    }

    // 2. Populate Static Nextion Fields
    set_nextion_text("PROG1", '0');
    set_nextion_text("PROG2", '1');
    set_nextion_text("VERB1", '2');
    set_nextion_text("VERB2", '3');
    set_nextion_text("NOUN1", '4');
    set_nextion_text("NOUN2", '5');
    set_nextion_text("R1_1", '+');
    set_nextion_text("R2_1", '+');
    set_nextion_text("R3_1", '+');

    // 3. Populate Numeric Register Positions
    char buffer[10];
    for (uint8_t i = 2; i <= 6; i++) {
        snprintf(buffer, sizeof(buffer), "R1_%d", i);
        set_nextion_text(buffer, '0' + (i - 1));

        snprintf(buffer, sizeof(buffer), "R2_%d", i);
        set_nextion_text(buffer, '0' + i);

        snprintf(buffer, sizeof(buffer), "R3_%d", i);
        set_nextion_text(buffer, '0' + ((i + 1) % 10));
    }

    // 4. Verify COMP ACTY State
    send_nextion_cmd("comp_acty.pic=3");
    delay(300);
    send_nextion_cmd("comp_acty.pic=2");

    Serial.println("Self-test complete.");
}