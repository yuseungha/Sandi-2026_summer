# Firmware build and pre-upload checks

No upload is authorized by this repository. Compile only after the operator has identified the board and created ignored `config/secrets.h` from `config/secrets.example.h`.

| Confirmed board | D10 / SDA GPIO | D9 / SCL GPIO |
|---|---:|---:|
| ESP32-C3 SuperMini | GPIO10 | GPIO9 |
| XIAO ESP32C3 | GPIO10 | GPIO9 |
| XIAO ESP32S3 | GPIO9 | GPIO8 |

`config/board_profile.h` intentionally has no default: zero or multiple selected board macros stops compilation with `#error`. The current physical labels are SDA **D10** and SCL **D9**, not the prior classic-ESP32 GPIO21/GPIO22 reference.

1. With power off, check 3.3 V, GND, D10 SDA, D9 SCL, no external pull-up, and unobstructed sensor intake.
2. Set exactly one confirmed board profile macro in ignored `config/secrets.h`.
3. Compile `i2c_scan/` first; after separate upload authorization it prints profile/GPIO and detects `0x62` without starting periodic measurements.
4. Compile `esp32_scd40_node/`; do not upload without operator approval.

### GPIO9 strapping warning

On ESP32-C3 profiles D9 maps to GPIO9, a boot strapping pin. If reset gives no boot or serial output, stop and suspect GPIO9 being held LOW. Inspect the wiring and choose an alternative pin pair only with operator approval; this document does not authorize a wiring change.
