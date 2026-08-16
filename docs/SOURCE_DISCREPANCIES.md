# Source and contract discrepancies

| Item | Actual checked source | Repository handling |
|---|---|---|
| Current physical I2C wiring | Operator update: SDA board label D10, SCL board label D9; board model is not confirmed | Classic ESP32 GPIO21/22 is not used. A no-default board profile must map D9/D10 at compile time. |
| Old team wiring document | `devices/co2/docs/WIRING.md` says ESP-WROOM-32 GPIO21/22 | Retained only as historical evidence; invalid for this replacement board. |
| C-B6 TFLite binary | `sheepmeat/test` candidate lock names hashes, but the main tree has no C-B6 `.tflite`; no supplied source provides it | No model substitution. CLI exits `MODEL_ARTIFACT_UNAVAILABLE`. |
| Candidate lock file checksum | Acquisition contract pins `candidate_lock_sha256=5f7772ff26ca10ca95aa5216b45f3eebd96c2429b98a7ee66963ec4ea73c6fd2`; the checked reference clone's current file SHA-256 is `424b62c973a6c287876a81ec813cfa6f4bee23ff3926c8d2e9472cde6f0b06c8`, while its internal lock content identity is `7dd6a4c78731465d258e60d2f5e301df2f7b30dbdcc28addb99a0e72a4ec1a90` | Bundle preserves the frozen acquisition-contract values and reports the source mismatch; artifact acceptance needs an authoritative lock reconciliation. |
| Capture script path | Frozen fixture identity uses `scripts/capture_co2_c_c1t_session.py`, while this requested layout puts the implementation in `capture/` | A thin `scripts/` compatibility entrypoint preserves fixture identity and delegates to `capture/`. |
| Team legacy inference | `CO2Interpreter.predict(co2_slope, humidity, co2_ppm)` is a three-feature interface | C-B6 requires `[CO2, CO2_slope]`; verifier rejects legacy-contract selection. |
| Fresh-event deployment | Acquisition contract snapshot identifies team PR #19 as open and undeployed | Live collection stays exploratory. This repository does not re-check or merge that PR. |

The reference checkout was obtained at remote HEAD `efc7e2eb61a49e221ce0ebf6057b0c1617525ad1` on 2026-08-16. No team repository file was modified.
