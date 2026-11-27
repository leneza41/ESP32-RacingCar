/*
 * LawamyRacing - Firmware ESP32 DevKit + Puente H L298N (2 motorreductores)
 *
 * Compatible con Arduino IDE (ESP32 Board Package v2.x y v3.x).
 * Protocolo Socket TCP (Puerto 8888):
 *   CMD:<DIR>,<PWM_IZQ>,<PWM_DER>\n
 *   donde DIR es: F (Adelante), B (Atrás), L (Izquierda), R (Derecha), S (Alto)
 *
 * Conexiones actuales (todos pines seguros de salida/PWM en ESP32):
 *   L298N ENA (retirar jumper) -> GPIO 26
 *   L298N IN1                  -> GPIO 25
 *   L298N IN2                  -> GPIO 33
 *   L298N IN3                  -> GPIO 32
 *   L298N IN4                  -> GPIO 27
 *   L298N ENB (retirar jumper) -> GPIO 14
 *   L298N GND                  -> GND del ESP32 + (-) Batería (OBLIGATORIO)
 */

#include <WiFi.h>

// ===================== CONFIGURACIÓN WIFI =====================
// true  = El ESP32 crea su propia red WiFi (ideal para salón de clases, IP fija 192.168.4.1)
// false = El ESP32 se conecta a tu router o hotspot del celular (revisa la IP en Monitor Serial)
#define USE_AP_MODE true

const char* AP_SSID     = "LawamyRacing_Car";
const char* AP_PASS     = "12345678";

const char* STA_SSID    = "TU_WIFI_AQUI";
const char* STA_PASS    = "TU_PASSWORD_AQUI";

const uint16_t SERVER_PORT = 8888;

// ===================== PINES PUENTE H L298N =====================
const int PIN_ENA = 26;  // PWM Motor Izquierdo
const int PIN_IN1 = 25;
const int PIN_IN2 = 33;

const int PIN_IN3 = 32;
const int PIN_IN4 = 27;
const int PIN_ENB = 14;  // PWM Motor Derecho

// Si alguna llanta gira al revés al avanzar, cambia a true sin recablear:
const bool INVERT_LEFT_MOTOR  = false;
const bool INVERT_RIGHT_MOTOR = false;

// ===================== CONFIGURACIÓN PWM Y SEGURIDAD =====================
const uint32_t PWM_FREQ       = 1000;  // 1 kHz ideal para motores amarillos TT + L298N
const uint8_t  PWM_RESOLUTION = 8;     // 8 bits (0 - 255)
const uint8_t  PWM_CH_LEFT    = 0;
const uint8_t  PWM_CH_RIGHT   = 1;

// Si pasan más de 500 ms sin recibir comando/heartbeat desde Python, frena los motores
const unsigned long WATCHDOG_TIMEOUT_MS = 500;

WiFiServer server(SERVER_PORT);
WiFiClient client;
String rxBuffer = "";
unsigned long lastCommandMs = 0;
bool motorsActive = false;

// ===================== ABSTRACCIÓN PWM (CORE 2.x y 3.x) =====================
void setupPwmPin(int pin, uint8_t channel) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  ledcAttach(pin, PWM_FREQ, PWM_RESOLUTION);
#else
  ledcSetup(channel, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(pin, channel);
#endif
}

void writePwm(int pin, uint8_t channel, uint8_t duty) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  ledcWrite(pin, duty);
#else
  ledcWrite(channel, duty);
#endif
}

// ===================== CONTROL DE MOTORES =====================
void setMotor(int pinA, int pinB, int pinPwm, uint8_t channel, int8_t dir, uint8_t speed, bool invert) {
  if (invert) {
    dir = -dir;
  }

  if (dir > 0) {
    digitalWrite(pinA, HIGH);
    digitalWrite(pinB, LOW);
    writePwm(pinPwm, channel, speed);
  } else if (dir < 0) {
    digitalWrite(pinA, LOW);
    digitalWrite(pinB, HIGH);
    writePwm(pinPwm, channel, speed);
  } else {
    digitalWrite(pinA, LOW);
    digitalWrite(pinB, LOW);
    writePwm(pinPwm, channel, 0);
  }
}

void stopMotors() {
  setMotor(PIN_IN1, PIN_IN2, PIN_ENA, PWM_CH_LEFT, 0, 0, INVERT_LEFT_MOTOR);
  setMotor(PIN_IN3, PIN_IN4, PIN_ENB, PWM_CH_RIGHT, 0, 0, INVERT_RIGHT_MOTOR);
  motorsActive = false;
}

void applyCommand(char dir, uint8_t pwmLeft, uint8_t pwmRight) {
  switch (dir) {
    case 'F':  // Adelante
      setMotor(PIN_IN1, PIN_IN2, PIN_ENA, PWM_CH_LEFT, +1, pwmLeft, INVERT_LEFT_MOTOR);
      setMotor(PIN_IN3, PIN_IN4, PIN_ENB, PWM_CH_RIGHT, +1, pwmRight, INVERT_RIGHT_MOTOR);
      motorsActive = (pwmLeft > 0 || pwmRight > 0);
      break;

    case 'B':  // Atrás
      setMotor(PIN_IN1, PIN_IN2, PIN_ENA, PWM_CH_LEFT, -1, pwmLeft, INVERT_LEFT_MOTOR);
      setMotor(PIN_IN3, PIN_IN4, PIN_ENB, PWM_CH_RIGHT, -1, pwmRight, INVERT_RIGHT_MOTOR);
      motorsActive = (pwmLeft > 0 || pwmRight > 0);
      break;

    case 'L':  // Giro diferencial a la izquierda (sobre su eje)
      setMotor(PIN_IN1, PIN_IN2, PIN_ENA, PWM_CH_LEFT, -1, pwmLeft, INVERT_LEFT_MOTOR);
      setMotor(PIN_IN3, PIN_IN4, PIN_ENB, PWM_CH_RIGHT, +1, pwmRight, INVERT_RIGHT_MOTOR);
      motorsActive = (pwmLeft > 0 || pwmRight > 0);
      break;

    case 'R':  // Giro diferencial a la derecha (sobre su eje)
      setMotor(PIN_IN1, PIN_IN2, PIN_ENA, PWM_CH_LEFT, +1, pwmLeft, INVERT_LEFT_MOTOR);
      setMotor(PIN_IN3, PIN_IN4, PIN_ENB, PWM_CH_RIGHT, -1, pwmRight, INVERT_RIGHT_MOTOR);
      motorsActive = (pwmLeft > 0 || pwmRight > 0);
      break;

    case 'S':
    default:
      stopMotors();
      break;
  }
}

void processLine(String line) {
  line.trim();
  if (!line.startsWith("CMD:")) {
    return;
  }

  // Formato esperado: CMD:F,190,185
  int firstComma  = line.indexOf(',', 4);
  int secondComma = line.indexOf(',', firstComma + 1);
  if (firstComma < 0 || secondComma < 0) {
    return;
  }

  char dir = line.charAt(4);
  int pwmL = constrain(line.substring(firstComma + 1, secondComma).toInt(), 0, 255);
  int pwmR = constrain(line.substring(secondComma + 1).toInt(), 0, 255);

  lastCommandMs = millis();
  applyCommand(dir, (uint8_t)pwmL, (uint8_t)pwmR);

  Serial.printf("[RX] DIR=%c | PWM_L=%d | PWM_R=%d\n", dir, pwmL, pwmR);
}

// ===================== SETUP Y LOOP =====================
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n=== LawamyRacing ESP32 Iniciando ===");

  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);
  pinMode(PIN_IN3, OUTPUT);
  pinMode(PIN_IN4, OUTPUT);

  setupPwmPin(PIN_ENA, PWM_CH_LEFT);
  setupPwmPin(PIN_ENB, PWM_CH_RIGHT);
  stopMotors();

#if USE_AP_MODE
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.print("[WIFI AP] Red creada: ");
  Serial.println(AP_SSID);
  Serial.print("[WIFI AP] Password:   ");
  Serial.println(AP_PASS);
  Serial.print("[WIFI AP] IP ESP32:   ");
  Serial.println(WiFi.softAPIP());
#else
  WiFi.mode(WIFI_STA);
  WiFi.begin(STA_SSID, STA_PASS);
  Serial.print("[WIFI STA] Conectando a ");
  Serial.println(STA_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("[WIFI STA] Conectado! IP ESP32: ");
  Serial.println(WiFi.localIP());
#endif

  server.begin();
  server.setNoDelay(true);
  Serial.printf("[SOCKET] Servidor TCP escuchando en puerto %u\n", SERVER_PORT);
}

void loop() {
  // Aceptar nuevo cliente si no hay uno conectado
  if (!client || !client.connected()) {
    WiFiClient newClient = server.available();
    if (newClient) {
      if (client) {
        client.stop();
      }
      client = newClient;
      client.setNoDelay(true);
      rxBuffer = "";
      lastCommandMs = millis();
      Serial.println("[SOCKET] Cliente Python conectado.");
    }
  }

  // Leer comandos entrantes por línea
  if (client && client.connected()) {
    while (client.available() > 0) {
      char c = (char)client.read();
      if (c == '\n') {
        processLine(rxBuffer);
        rxBuffer = "";
      } else if (c != '\r' && rxBuffer.length() < 64) {
        rxBuffer += c;
      }
    }
  }

  // Watchdog de seguridad: detener motores si se pierde comunicación
  if (motorsActive && (millis() - lastCommandMs > WATCHDOG_TIMEOUT_MS)) {
    stopMotors();
    Serial.println("[SAFETY] Watchdog activado (>500ms sin señal): Motores detenidos.");
  }
}
