/*
 * SafeNest CO2-only ESP-WROOM-32 producer.
 *
 * Fresh-event invariants:
 * - same_event_id_is_cached_retransmission: true
 * - transport_freshness_is_sensor_freshness: false
 * - co2_valid_is_not_event_freshness: true
 *
 * The event id changes only in acceptSuccessfulMeasurement(), which is called
 * after SCD4x readMeasurement() succeeds. A periodic TCP resend never changes
 * it. `millis()` is producer-side monotonic time since ESP32 boot.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <SensirionI2cScd4x.h>

#if !__has_include("../config/secrets.h")
#error "Copy firmware/config/secrets.example.h to secrets.h and set deployment values before compiling."
#endif
#include "../config/secrets.h"
#include "../config/board_profile.h"

// -----------------------------------------------------------------------------
// Deployment configuration: network values and profile selection originate in
// firmware/config/secrets.h; physical GPIO pins are injected by board_profile.h.
// Reconfirm this entire block for the replacement board before any upload.
// -----------------------------------------------------------------------------
constexpr char WIFI_SSID[] = SAFENEST_WIFI_SSID;
constexpr char WIFI_PASSWORD[] = SAFENEST_WIFI_PASSWORD;
constexpr char DEVICE_ID[] = SAFENEST_DEVICE_ID;
constexpr char RPI_HOST[] = SAFENEST_RPI_HOST;
constexpr uint16_t RPI_PORT = SAFENEST_RPI_PORT;
constexpr bool USE_STATIC_IP = SAFENEST_USE_STATIC_IP;
constexpr char STATIC_IP[] = SAFENEST_STATIC_IP;
constexpr char STATIC_GATEWAY[] = SAFENEST_STATIC_GATEWAY;
constexpr char STATIC_SUBNET[] = SAFENEST_STATIC_SUBNET;
constexpr char STATIC_DNS[] = SAFENEST_STATIC_DNS;
constexpr int PIN_I2C_SDA = SCD40_SDA_PIN;
constexpr int PIN_I2C_SCL = SCD40_SCL_PIN;

constexpr uint8_t SCD4X_ADDRESS = 0x62;
constexpr uint32_t CO2_POLL_PERIOD_MS = 250;
constexpr uint32_t CO2_STALE_MS = 15000;
constexpr uint32_t TELEMETRY_PERIOD_MS = 1000;
constexpr uint32_t WIFI_RETRY_PERIOD_MS = 5000;
constexpr uint8_t PROTOCOL_VERSION = 1;
constexpr uint8_t PACKET_TELEMETRY_JSON = 1;
constexpr size_t PACKET_HEADER_SIZE = 16;

SensirionI2cScd4x scd4x;
WiFiClient piClient;

bool co2Started = false;
bool firstMeasurementObserved = false;
bool lastStaleState = true;
uint16_t co2Ppm = 0;
uint32_t lastCo2SuccessMs = 0;
uint32_t co2MeasurementEventId = 0;
uint32_t co2MeasurementMonotonicMs = 0;
bool co2MeasurementEventValid = false;
uint32_t telemetrySequence = 0;
uint32_t lastCo2PollMs = 0;
uint32_t lastTelemetryMs = 0;
uint32_t lastWifiAttemptMs = 0;

bool due(uint32_t now, uint32_t &last, uint32_t period) {
  if (static_cast<uint32_t>(now - last) < period) return false;
  last = now;
  return true;
}

bool i2cPresent(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

bool co2IsValid(uint32_t now) {
  return lastCo2SuccessMs != 0 &&
      static_cast<uint32_t>(now - lastCo2SuccessMs) <= CO2_STALE_MS;
}

void logStaleTransition(uint32_t now) {
  const bool stale = !co2IsValid(now);
  if (stale != lastStaleState) {
    Serial.printf("[CO2_STALE_TRANSITION] state=%s age_ms=%lu event_id=%lu\n",
                  stale ? "STALE" : "LIVE",
                  static_cast<unsigned long>(now - lastCo2SuccessMs),
                  static_cast<unsigned long>(co2MeasurementEventId));
    lastStaleState = stale;
  }
}

// This is the only event-id increment site. Do not increment it in telemetry,
// polling, reconnect, timer, retry, or error paths.
void acceptSuccessfulMeasurement(uint16_t freshCo2Ppm, uint32_t now) {
  co2Ppm = freshCo2Ppm;
  lastCo2SuccessMs = now;
  co2MeasurementEventId += 1;
  co2MeasurementMonotonicMs = now;
  co2MeasurementEventValid = true;
  if (!firstMeasurementObserved) {
    Serial.printf("[CO2_FIRST_MEASUREMENT] ppm=%u event_id=%lu\n", co2Ppm,
                  static_cast<unsigned long>(co2MeasurementEventId));
    firstMeasurementObserved = true;
  } else {
    Serial.printf("[CO2_FRESH_READ] ppm=%u event_id=%lu monotonic_ms=%lu\n",
                  co2Ppm, static_cast<unsigned long>(co2MeasurementEventId),
                  static_cast<unsigned long>(co2MeasurementMonotonicMs));
  }
}

void initializeCo2() {
  if (!i2cPresent(SCD4X_ADDRESS)) {
    Serial.println("[CO2_I2C_MISSING] address=0x62; check 3.3V/GND/GPIO21/GPIO22");
    return;
  }
  scd4x.begin(Wire, SCD41_I2C_ADDR_62);
  scd4x.stopPeriodicMeasurement();
  delay(500);  // Setup only; normal runtime uses millis scheduling.
  const int16_t startError = scd4x.startPeriodicMeasurement();
  if (startError != 0) {
    Serial.printf("[CO2_START_ERROR] startPeriodicMeasurement=%d\n", startError);
    return;
  }
  co2Started = true;
  Serial.println("[CO2_FIRST_MEASUREMENT_PENDING] periodic mode started; first measurement takes about 5 seconds");
}

void pollCo2(uint32_t now) {
  if (!co2Started || !due(now, lastCo2PollMs, CO2_POLL_PERIOD_MS)) return;

  bool ready = false;
  const int16_t readyError = scd4x.getDataReadyStatus(ready);
  if (readyError != 0) {
    Serial.printf("[CO2_READY_STATUS_ERROR] code=%d\n", readyError);
    return;
  }
  if (!ready) return;

  uint16_t newCo2Ppm = 0;
  float temperatureC = NAN;
  float humidityRh = NAN;
  const int16_t readError = scd4x.readMeasurement(newCo2Ppm, temperatureC, humidityRh);
  if (readError == 0 && newCo2Ppm != 0) {
    acceptSuccessfulMeasurement(newCo2Ppm, now);
  } else {
    Serial.printf("[CO2_READ_ERROR] readMeasurement=%d ppm=%u; event_id remains %lu\n",
                  readError, newCo2Ppm,
                  static_cast<unsigned long>(co2MeasurementEventId));
  }
}

void putU16(uint8_t *out, uint16_t value) {
  out[0] = static_cast<uint8_t>(value >> 8);
  out[1] = static_cast<uint8_t>(value);
}

void putU32(uint8_t *out, uint32_t value) {
  out[0] = static_cast<uint8_t>(value >> 24);
  out[1] = static_cast<uint8_t>(value >> 16);
  out[2] = static_cast<uint8_t>(value >> 8);
  out[3] = static_cast<uint8_t>(value);
}

void makeHeader(uint8_t *header, uint32_t sequence, uint32_t payloadLength) {
  memcpy(header, "SNST", 4);
  header[4] = PROTOCOL_VERSION;
  header[5] = PACKET_TELEMETRY_JSON;
  putU16(header + 6, 0);
  putU32(header + 8, sequence);
  putU32(header + 12, payloadLength);
}

bool writeAll(const uint8_t *data, size_t length) {
  size_t writtenTotal = 0;
  while (writtenTotal < length && piClient.connected()) {
    const size_t written = piClient.write(data + writtenTotal, length - writtenTotal);
    if (written == 0) return false;
    writtenTotal += written;
  }
  return writtenTotal == length;
}

bool sendTelemetry(uint32_t now) {
  const bool co2Valid = co2IsValid(now);
  char co2Value[16];
  if (co2Valid) {
    snprintf(co2Value, sizeof(co2Value), "%u", co2Ppm);
  } else {
    strlcpy(co2Value, "null", sizeof(co2Value));
  }

  // Required fields remain in the sensors object so the Pi can pass them
  // through verbatim. co2_valid is intentionally distinct from event freshness.
  char json[640];
  const uint32_t sequence = ++telemetrySequence;
  const int length = snprintf(
      json, sizeof(json),
      "{\"schema\":\"safenest.telemetry.v1\",\"device_id\":\"%s\","
      "\"seq\":%lu,\"uptime_ms\":%lu,\"sensors\":{"
      "\"co2_ppm\":%s,\"valid\":{\"co2\":%s},"
      "\"co2_measurement_event_id\":%lu,"
      "\"co2_measurement_monotonic_ms\":%lu,"
      "\"co2_measurement_event_valid\":%s}}",
      DEVICE_ID, static_cast<unsigned long>(sequence),
      static_cast<unsigned long>(now), co2Value, co2Valid ? "true" : "false",
      static_cast<unsigned long>(co2MeasurementEventId),
      static_cast<unsigned long>(co2MeasurementMonotonicMs),
      co2MeasurementEventValid ? "true" : "false");
  if (length <= 0 || static_cast<size_t>(length) >= sizeof(json)) {
    Serial.println("[CO2_TELEMETRY_ERROR] JSON buffer overflow");
    return false;
  }
  uint8_t header[PACKET_HEADER_SIZE];
  makeHeader(header, sequence, static_cast<uint32_t>(length));
  return writeAll(header, sizeof(header)) &&
      writeAll(reinterpret_cast<const uint8_t *>(json), static_cast<size_t>(length));
}

void maintainWifi(uint32_t now) {
  if (WiFi.status() == WL_CONNECTED) return;
  if (!due(now, lastWifiAttemptMs, WIFI_RETRY_PERIOD_MS)) return;
  Serial.printf("[WIFI_RETRY] ssid=%s\n", WIFI_SSID);
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void setupWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  if (USE_STATIC_IP) {
    IPAddress ip, gateway, subnet, dns;
    if (!ip.fromString(STATIC_IP) || !gateway.fromString(STATIC_GATEWAY) ||
        !subnet.fromString(STATIC_SUBNET) || !dns.fromString(STATIC_DNS) ||
        !WiFi.config(ip, gateway, subnet, dns)) {
      Serial.println("[WIFI_STATIC_IP_ERROR] static configuration rejected; correct secrets.h");
    }
  }
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("[CO2_BOOT] profile=%s SDA_GPIO=%d(D10) SCL_GPIO=%d(D9)\n",
                SAFENEST_BOARD_PROFILE_NAME, PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.begin(SCD40_SDA_PIN, SCD40_SCL_PIN);
  Wire.setClock(400000);
  initializeCo2();
  setupWifi();
}

void loop() {
  const uint32_t now = millis();
  maintainWifi(now);
  pollCo2(now);
  logStaleTransition(now);

  if (WiFi.status() == WL_CONNECTED &&
      due(now, lastTelemetryMs, TELEMETRY_PERIOD_MS)) {
    if (!piClient.connected() && !piClient.connect(RPI_HOST, RPI_PORT, 1500)) {
      Serial.printf("[PI_CONNECT_ERROR] host=%s port=%u\n", RPI_HOST, RPI_PORT);
    }
    if (piClient.connected() && !sendTelemetry(now)) {
      Serial.println("[PI_SEND_ERROR] closing TCP client");
      piClient.stop();
    }
  }
  delay(1);
}
