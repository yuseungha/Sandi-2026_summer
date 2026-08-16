# SafeNest SCD40 exploratory-session runbook

**Scope:** operator-only physical procedure. This repository does not authorize firmware upload, device execution, formal protocol collection, accuracy/F1 calculation, Git push, or PR creation. Until fresh-event PR #19 is deployed and verified, every live bundle is `PRE_DEPLOYMENT_EXPLORATORY_REAL_DEVICE_EVIDENCE` and `formal_endpoint_h150_claim` remains blocked.

## 0. Decide and stop conditions

1. Declare one stable scenario before powering on: `VACANT_STABLE` or `OCCUPIED_STABLE`; the label comes from observation, never CO2 or model output.
2. Stop before proceeding if the board model is unknown, 3.3 V/GND/D10/D9 wiring is uncertain, a short/heat/smell is observed, or any connection contradicts the configuration.
3. Record the operator ID, location ID, room size, sensor position, ventilation state, window/door state, and observed person-count changes; person count is an observation, not a model output.

## 1. Wiring and board-profile check

1. With power disconnected, verify SCD40 3.3 V, shared GND, SDA **D10**, SCL **D9**, no external pull-up, intake unobstructed, and no direct breath/moisture on the sensor.
2. Identify the board model. In `firmware/config/secrets.h`, select exactly one profile; no profile intentionally fails compilation.
3. Compile and, only after separate upload approval, use `firmware/i2c_scan/` before the main sender. Its serial log must state the selected profile/GPIO mapping and `0x62` detection.
4. For C3 profiles, stop on boot silence: D9 is GPIO9 and may cause boot-strapping trouble if pulled LOW. Do not rewire unless the operator approves the change.

## 2. Network and receiver check

1. Confirm the ESP32's actual assigned IP from the router/serial log; do not assume a historical address.
2. On the intended Pi, start the receiver only after confirming TCP 9000 and HTTP 8080 are available:

```bash
cd <Sandi-2026_summer>
python3 pi/safenest_pi_service.py --sensor-port 9000 --http-port 8080
```

3. Compare `[PI_CONNECTED] <peer-ip>:<port>` with the verified ESP32 IP.
4. Query health and retain the unedited response:

```bash
curl -sS http://<verified-pi-ip>:8080/health
```

5. Proceed only if the three `co2_measurement_*` fields are present and copied values look consistent. `fresh=true` means transport-recent only; it does not prove a new SCD40 measurement.

## 3. Capture one session

1. Leave the scenario stable for at least 300 seconds and keep the operator's independent observation record.
2. Start the raw capture on the Pi or another approved host:

```bash
cd <Sandi-2026_summer>
python3 capture/capture_co2_session.py \
  --url http://<verified-pi-ip>:8080/health \
  --duration-sec 300 --interval-sec 1 --timeout-sec 3 \
  --scenario VACANT_STABLE \
  --output-dir sessions --operator-id <operator-id> --location-id <location-id>
```

3. For a stable occupied observation, change only `--scenario OCCUPIED_STABLE`. Do not change, delete, fill, deduplicate, or edit rows when repeated values, stale state, errors, or reconnections occur.
4. On unexpected reset, location change, or uncertain scenario, stop the capture and preserve the partial bundle. Start a new session only after recording the boundary.

## 4. Finalize and verify the bundle

1. The capture tool creates exactly seven bundle files and writes its own SHA-256 list after finalization.
2. Independently verify its values without overwriting `checksums.sha256`:

```bash
cd sessions/<generated-session-id>
shasum -a 256 raw_measurements.jsonl ground_truth_events.jsonl failure_events.jsonl deviation_events.jsonl operator_notes.md session_manifest.json
cat checksums.sha256
```

3. Keep the raw JSONL unchanged. Add factual observations only through the operator-note process before finalization; after finalization, record corrections in a separate derived note rather than rewriting evidence.
4. Run the offline verifier only as a contract/slope diagnostic. It must currently report `MODEL_ARTIFACT_UNAVAILABLE`; do not substitute the legacy three-input model.

## 5. Safe stop

1. Stop capture with Ctrl+C only after the current raw write completes, then stop the Pi service with Ctrl+C.
2. Keep the bundle directory intact, including empty failure/deviation logs.
3. Report the bundle path, independent scenario observation, observed transport interruptions, checksums result, and that the session remains exploratory—not formal model validation.
