from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_firmware_fresh_event_and_board_profile_contract() -> None:
    source = (ROOT / "firmware" / "esp32_scd40_node" / "esp32_scd40_node.ino").read_text(encoding="utf-8")
    profile = (ROOT / "firmware" / "config" / "board_profile.h").read_text(encoding="utf-8")
    scanner = (ROOT / "firmware" / "i2c_scan" / "i2c_scan.ino").read_text(encoding="utf-8")
    assert source.count("co2MeasurementEventId += 1;") == 1
    assert "if (readError == 0 && newCo2Ppm != 0)" in source
    assert "Wire.begin(SCD40_SDA_PIN, SCD40_SCL_PIN);" in source
    for invariant in (
        "same_event_id_is_cached_retransmission: true",
        "transport_freshness_is_sensor_freshness: false",
        "co2_valid_is_not_event_freshness: true",
    ):
        assert invariant in source
    assert "#error" in profile
    assert "SCD40_SDA_PIN 10" in profile
    assert "SCD40_SCL_PIN 9" in profile
    assert "Wire.begin(SCD40_SDA_PIN, SCD40_SCL_PIN);" in scanner
    assert "0x62" in scanner


def test_pi_passes_event_fields_without_filling() -> None:
    sys.path.insert(0, str(ROOT / "pi"))
    import safenest_pi_service as service

    store = service.SensorStore(15)
    original = {
        "schema": "safenest.telemetry.v1",
        "device_id": "esp32-test",
        "seq": 1,
        "uptime_ms": 99,
        "sensors": {
            "co2_ppm": 650,
            "co2_measurement_event_id": 3,
            "co2_measurement_monotonic_ms": 99,
            "co2_measurement_event_valid": True,
            "valid": {"co2": True},
        },
    }
    store.record_telemetry(original)
    sensors = store.snapshot()["sensors"]
    for key in service.EVENT_FIELDS:
        assert sensors[key] == original["sensors"][key]
