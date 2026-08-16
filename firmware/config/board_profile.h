#pragma once

// SCD40 physical wiring was confirmed by board silkscreen only:
// SDA -> D10, SCL -> D9. The board model determines their GPIO numbers.
// There is deliberately no default. A wrong classic-ESP32 21/22 default could
// silently address the wrong pins, so an unselected or ambiguous profile fails.

#if (defined(SAFENEST_BOARD_PROFILE_ESP32_C3_SUPERMINI) + \
     defined(SAFENEST_BOARD_PROFILE_XIAO_ESP32C3) + \
     defined(SAFENEST_BOARD_PROFILE_XIAO_ESP32S3)) != 1
#error "Select exactly one SAFENEST_BOARD_PROFILE_* macro in firmware/config/secrets.h"
#endif

#if defined(SAFENEST_BOARD_PROFILE_ESP32_C3_SUPERMINI)
#define SAFENEST_BOARD_PROFILE_NAME "ESP32-C3 SuperMini"
#define SCD40_SDA_PIN 10  // D10
#define SCD40_SCL_PIN 9   // D9; GPIO9 is a boot strapping pin on ESP32-C3
#elif defined(SAFENEST_BOARD_PROFILE_XIAO_ESP32C3)
#define SAFENEST_BOARD_PROFILE_NAME "XIAO ESP32C3"
#define SCD40_SDA_PIN 10  // D10
#define SCD40_SCL_PIN 9   // D9; GPIO9 is a boot strapping pin on ESP32-C3
#elif defined(SAFENEST_BOARD_PROFILE_XIAO_ESP32S3)
#define SAFENEST_BOARD_PROFILE_NAME "XIAO ESP32S3"
#define SCD40_SDA_PIN 9   // D10
#define SCD40_SCL_PIN 8   // D9
#endif
