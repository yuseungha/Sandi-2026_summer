# ESP32 SCD40 fresh-event producer

## Build-only procedure

1. Copy `firmware/config/secrets.example.h` to ignored `firmware/config/secrets.h`; enter the verified 2.4 GHz SSID/password, Pi address/port, device ID, and optional static-IP plan.
2. Confirm the board model, then select exactly one profile macro. The physical wiring is **SDA D10** and **SCL D9**; GPIO is profile-dependent and no profile has a default.
3. Keep the board unpowered while checking SCD40 `3.3V`, common GND, D10 SDA, D9 SCL, and no external I2C pull-up.
4. Compile and, only after separate operator authorization, run `firmware/i2c_scan/` first. It prints profile/GPIO and whether `0x62` is detected.
5. Select the matching board in Arduino IDE or Arduino CLI, install the Sensirion SCD4x library that provides `SensirionI2cScd4x.h`, then compile the producer only.

Example compile command after the board core and library are installed:

```bash
arduino-cli compile --fqbn <confirmed-board-fqbn> firmware/esp32_scd40_node
```

Expected serial tags after an authorized upload are `[CO2_I2C_MISSING]`, `[CO2_START_ERROR]`, `[CO2_FIRST_MEASUREMENT_PENDING]`, `[CO2_FIRST_MEASUREMENT]`, `[CO2_FRESH_READ]`, and `[CO2_STALE_TRANSITION]`. A repeated telemetry packet must keep the same event ID; only a successful `readMeasurement()` advances it.

## D9/D10 profile mapping

| Confirmed board | D10 → SDA GPIO | D9 → SCL GPIO |
|---|---:|---:|
| ESP32-C3 SuperMini | GPIO10 | GPIO9 |
| XIAO ESP32C3 | GPIO10 | GPIO9 |
| XIAO ESP32S3 | GPIO9 | GPIO8 |

## GPIO9 boot-strapping troubleshooting

On ESP32-C3 profiles, D9 is GPIO9, a boot-strapping pin. If reset produces no boot or serial output, suspect GPIO9 being held LOW and stop. Inspect the pull level and consider an alternative approved I2C pin pair; do not rewire merely because this guide suggests it.
