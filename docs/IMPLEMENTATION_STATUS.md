# C-C1T implementation status

## TASK 1 — repository bootstrap

- 확인된 것: Empty target checkout now contains the requested CO2-only layout and no team checkout was modified.
- 확인 안 된 것: Remote push/first commit state is not created; operator approval is required for push.
- 다음에 필요한 것: Review the local diff, then authorize a scoped first commit if desired.

## TASK 2 — ESP32 fresh-event firmware

- 확인된 것: Event fields, successful-read-only increment site, D10/D9 board profiles, and I2C scan sketch are implemented and source-tested.
- 확인 안 된 것: Board identity, D9/D10 electrical mapping, library/core compatibility, compile result, upload, and real `0x62` detection are not verified.
- 다음에 필요한 것: Operator identifies the board, selects one profile, then authorizes a compile-only check.

## TASK 3 — Pi pass-through and capture

- 확인된 것: Pi preserves the three event fields and capture creates immutable seven-file dry-run/live bundle formats using standard library only.
- 확인 안 된 것: No Pi process, network endpoint, or physical sensor session was started.
- 다음에 필요한 것: Operator follows the runbook after an approved deployment decision.

## TASK 4 — offline verifier

- 확인된 것: Two-feature C-B6 contract, H150 no-fill calculation, legacy mismatch refusal, and INT8 saturation reporting are implemented.
- 확인 안 된 것: C-B6 TFLite binary is unavailable, so runtime tensor validation and deterministic inference are not run.
- 다음에 필요한 것: Obtain an authoritative locked C-B6 binary and reconcile candidate-lock checksum identity.

## TASK 5 — dry-run tests

- 확인된 것: Seven contract cases plus firmware/Pi and verifier boundary tests are present.
- 확인 안 된 것: `pytest` 10 passed is software-only evidence and does not validate a Pi, ESP32, wiring, or SCD40.
- 다음에 필요한 것: Re-run the same suite after any contract or fixture change, then keep real-device work operator-controlled.

## TASK 6 — operator runbook

- 확인된 것: The runbook includes D10/D9 wiring, GPIO9 strapping stop condition, Pi peer check, 300-second capture, checksum verification, environment observations, and safe stop.
- 확인 안 된 것: An operator has not performed the sequence; no physical session is claimed.
- 다음에 필요한 것: Operator executes one exploratory session only after the separate hardware approvals.
