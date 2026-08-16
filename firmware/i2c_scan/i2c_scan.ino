/* Independent pre-upload I2C scanner for the selected SafeNest board profile. */

#include <Arduino.h>
#include <Wire.h>

#if !__has_include("../config/secrets.h")
#error "Copy firmware/config/secrets.example.h to secrets.h and select a board profile first."
#endif
#include "../config/secrets.h"
#include "../config/board_profile.h"

void setup() {
  Serial.begin(115200);
  delay(300);
  Wire.begin(SCD40_SDA_PIN, SCD40_SCL_PIN);
  Serial.printf("[I2C_SCAN_BOOT] profile=%s SDA_GPIO=%d(D10) SCL_GPIO=%d(D9)\n",
                SAFENEST_BOARD_PROFILE_NAME, SCD40_SDA_PIN, SCD40_SCL_PIN);
  bool foundSCD40 = false;
  for (uint8_t address = 1; address < 127; ++address) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      Serial.printf("[I2C_FOUND] 0x%02X%s\n", address,
                    address == 0x62 ? " SCD40_EXPECTED" : "");
      foundSCD40 = foundSCD40 || address == 0x62;
    }
  }
  Serial.printf("[I2C_SCAN_RESULT] scd40_0x62=%s\n", foundSCD40 ? "FOUND" : "NOT_FOUND");
}

void loop() {
  delay(1000);
}
