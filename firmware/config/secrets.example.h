#pragma once

// Copy this file to secrets.h, replace every deployment value, and keep it local.
// The supplied values are placeholders, not confirmed deployment facts.
#define SAFENEST_WIFI_SSID "REPLACE_WITH_2G4_SSID"
#define SAFENEST_WIFI_PASSWORD "REPLACE_WITH_WIFI_PASSWORD"
#define SAFENEST_DEVICE_ID "REPLACE_WITH_ESP32_ID"
#define SAFENEST_RPI_HOST "REPLACE_WITH_PI_IPV4"
#define SAFENEST_RPI_PORT 9000

// Set true only after confirming the LAN addressing plan. DHCP is the safe default.
#define SAFENEST_USE_STATIC_IP false
#define SAFENEST_STATIC_IP "REPLACE_WITH_ESP32_STATIC_IPV4"
#define SAFENEST_STATIC_GATEWAY "REPLACE_WITH_GATEWAY_IPV4"
#define SAFENEST_STATIC_SUBNET "255.255.255.0"
#define SAFENEST_STATIC_DNS "REPLACE_WITH_DNS_IPV4"

// Select exactly one after confirming the board model. Do not uncomment more
// than one line. Leaving all lines disabled intentionally makes #error fail.
// #define SAFENEST_BOARD_PROFILE_ESP32_C3_SUPERMINI 1
// #define SAFENEST_BOARD_PROFILE_XIAO_ESP32C3 1
// #define SAFENEST_BOARD_PROFILE_XIAO_ESP32S3 1
