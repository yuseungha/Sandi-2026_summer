# SafeNest CO2 C-C1T acquisition tooling

> **Current boundary:** `C_B6_REDUCED_CO2_SLOPE_CANDIDATE_001` TFLite binaries are not available in this repository, and team PR #19 fresh-event observability is not deployed to team `main`. This repository supports dry-run and exploratory real-device capture only; it must not be used to claim formal `ENDPOINT_H150` eligibility, accuracy, or F1.

SCD40 measurements are sent from an ESP-WROOM-32 to a Raspberry Pi, retained as an immutable seven-file session bundle, and checked by an offline Pi-side verification CLI. mmWave and Thermal are outside this repository's modification scope.

## Hardware and transport

| Item | Configuration status |
|---|---|
| Sensor | SCD40, I2C address `0x62` |
| Power | 3.3 V only; shared GND; no external SDA/SCL pull-up |
| I2C wiring | SDA board silkscreen D10, SCL board silkscreen D9; select a confirmed GPIO profile before build |
| Transport | SafeNest v1 TCP (`SNST`, port configured in ignored `secrets.h`) |
| Pi endpoint | `/health` is served by `pi/safenest_pi_service.py`; verify its actual address before use |

## Repository layout

| Path | Purpose |
|---|---|
| `firmware/esp32_scd40_node/` | CO2-only ESP32 sender with fresh-event fields |
| `pi/` | TCP receiver and `/health` pass-through service |
| `capture/` | Standard-library session bundle capture tool |
| `verify/` | Offline C-B6 contract, slope, and model-artifact checker |
| `fixtures/` | Deterministic source inputs and expected bundle reference |
| `sessions/` | Versionable immutable capture bundles, created by the tool |
| `tests/` | Hardware-free contract tests |

## Quick software verification

```powershell
cd 'C:\Users\small\OneDrive\문서\00_경희대학교\01_대회\임베디드 SW 경진대회\00_AI_Develope\01_Repositories\Sandi-2026_summer'
python -m pytest -q
python verify/verify_co2_model.py --session-dir fixtures/CO2C1R-20260815-CODEX-S001
```

The second command must report `MODEL_ARTIFACT_UNAVAILABLE` until the locked C-B6 artifact is supplied and its SHA-256 matches the contract. `dry_run_pass_is_not_real_sensor_validation: true`.

## Safety and evidence rules

- `co2_measurement_event_id` changes only after a successful `readMeasurement()`; transport packets never make a sensor measurement fresh.
- The Pi passes the three event fields through without manufacturing or filling them.
- Capture never interpolates, forward-fills, infers ground truth from CO2/model output, deletes errors, or rewrites closed raw files.
- All live capture manifests use `PRE_DEPLOYMENT_EXPLORATORY_REAL_DEVICE_EVIDENCE`; this is not a formal validation claim while PR #19 remains undeployed.
- See [the operator runbook](docs/OPERATOR_RUNBOOK.md) for the operator-only hardware sequence and [source discrepancies](docs/SOURCE_DISCREPANCIES.md) for upstream mismatches.
