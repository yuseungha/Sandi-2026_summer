from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "capture"))
import capture_co2_session as capture  # noqa: E402


def run_fixture(tmp_path: Path, name: str, scenario: str = "VACANT_STABLE") -> Path:
    args = SimpleNamespace(
        url="http://127.0.0.1:8080/health",
        duration_sec=60.0,
        interval_sec=1.0,
        timeout_sec=3.0,
        scenario=scenario,
        output_dir=tmp_path,
        operator_id="codex",
        location_id="fixture-room",
        fixture=ROOT / "fixtures" / name,
    )
    return capture.run_capture(args)


def jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def assert_expected_fields(expected: object, actual: object) -> None:
    """Reference fields must match; required new fields may extend the old fixture."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for key, value in expected.items():
            assert key in actual
            assert_expected_fields(value, actual[key])
    elif isinstance(expected, list):
        assert isinstance(actual, list)
        assert len(expected) == len(actual)
        for old, new in zip(expected, actual):
            assert_expected_fields(old, new)
    else:
        assert expected == actual


def test_fresh_event(tmp_path: Path) -> None:
    session = run_fixture(tmp_path, "valid_session_input.jsonl")
    first = jsonl(session / "raw_measurements.jsonl")[0]
    assert first["sensor_measurement_freshness"] == "FRESH_EVENT"
    assert first["sensor_read_status"] == "SUCCESSFUL_FRESH_READ"


def test_cached_retransmission_same_event_id(tmp_path: Path) -> None:
    session = run_fixture(tmp_path, "valid_session_input.jsonl")
    second = jsonl(session / "raw_measurements.jsonl")[1]
    assert second["sensor_measurement_freshness"] == "CACHED_RETRANSMISSION"
    assert second["measurement_event_id"] == "safenest-esp32-01:1"


def test_second_fresh_event_in_chronology(tmp_path: Path) -> None:
    session = run_fixture(tmp_path, "valid_session_input.jsonl")
    third = jsonl(session / "raw_measurements.jsonl")[2]
    manifest = json.loads((session / "session_manifest.json").read_text(encoding="utf-8"))
    assert third["sensor_measurement_freshness"] == "FRESH_EVENT"
    assert third["sensor_event_id"] == 2
    assert manifest["counts"]["fresh_events"] == 2


def test_missing_sensor_event_marker(tmp_path: Path) -> None:
    session = run_fixture(tmp_path, "missing_event_marker.jsonl")
    record = jsonl(session / "raw_measurements.jsonl")[0]
    assert record["sensor_measurement_freshness"] == "MISSING_EVENT_MARKER"
    assert record["missing_or_error_state"] == "MISSING_SENSOR_EVENT_MARKER"
    assert jsonl(session / "failure_events.jsonl")[0]["failure_state"] == "MISSING_SENSOR_EVENT_MARKER"


def test_transport_failure(tmp_path: Path) -> None:
    session = run_fixture(tmp_path, "transport_failure.jsonl")
    record = jsonl(session / "raw_measurements.jsonl")[0]
    assert record["sensor_read_status"] == "TRANSPORT_FAILURE"
    assert record["raw_received_payload"] is None
    assert jsonl(session / "failure_events.jsonl")[0]["failure_state"].startswith("URLError:")


def test_independent_ground_truth_vacant_or_occupied(tmp_path: Path) -> None:
    session = run_fixture(tmp_path, "valid_session_input.jsonl", scenario="OCCUPIED_STABLE")
    ground_truth = jsonl(session / "ground_truth_events.jsonl")[0]
    assert ground_truth["label"] == "OCCUPIED"
    assert ground_truth["source"] == "CONTROLLED_PERSON_PRESENT"
    assert ground_truth["derived_from_sensor_or_model"] is False


def test_finalization_and_checksum_verification(tmp_path: Path) -> None:
    session = run_fixture(tmp_path, "valid_session_input.jsonl")
    expected = ROOT / "fixtures" / "CO2C1R-20260815-CODEX-S001"
    assert_expected_fields(jsonl(expected / "raw_measurements.jsonl"), jsonl(session / "raw_measurements.jsonl"))
    assert_expected_fields(
        jsonl(expected / "ground_truth_events.jsonl"),
        jsonl(session / "ground_truth_events.jsonl"),
    )
    assert_expected_fields(jsonl(expected / "failure_events.jsonl"), jsonl(session / "failure_events.jsonl"))
    assert_expected_fields(jsonl(expected / "deviation_events.jsonl"), jsonl(session / "deviation_events.jsonl"))
    assert_expected_fields(
        json.loads((expected / "session_manifest.json").read_text(encoding="utf-8")),
        json.loads((session / "session_manifest.json").read_text(encoding="utf-8")),
    )
    assert (expected / "operator_notes.md").read_text(encoding="utf-8") == (
        session / "operator_notes.md"
    ).read_text(encoding="utf-8")
    manifest = json.loads((session / "session_manifest.json").read_text(encoding="utf-8"))
    assert manifest["evidence_class"] == capture.EVIDENCE_CLASS
    for line in (session / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        digest, filename = line.split("  ", 1)
        assert digest == hashlib.sha256((session / filename).read_bytes()).hexdigest()
