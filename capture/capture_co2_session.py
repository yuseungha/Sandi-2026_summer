#!/usr/bin/env python3
"""Capture immutable C-C1T CO2 raw bundles from Pi /health or JSONL fixtures.

Only Python's standard library is used. This program records the raw layer; it
does not calculate slope, run a model, interpolate, forward-fill, or infer a
ground-truth label from sensor/model data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROTOCOL_ID = "CO2_C_C1R_REDUCED_MEASUREMENT_PROTOCOL_001"
PROTOCOL_VERSION = "1.0.0"
TARGET_CANDIDATE_ID = "C_B6_REDUCED_CO2_SLOPE_CANDIDATE_001"
CANDIDATE_LOCK_SHA256 = "5f7772ff26ca10ca95aa5216b45f3eebd96c2429b98a7ee66963ec4ea73c6fd2"
CANDIDATE_LOCK_CONTENT_SHA256 = "7dd6a4c78731465d258e60d2f5e301df2f7b30dbdcc28addb99a0e72a4ec1a90"
EVIDENCE_CLASS = "PRE_DEPLOYMENT_EXPLORATORY_REAL_DEVICE_EVIDENCE"
# Frozen C-C1T identity is retained for source-bundle compatibility. The thin
# `scripts/` wrapper delegates to this implementation; see SOURCE_DISCREPANCIES.
SCRIPT_IDENTITY = "scripts/capture_co2_c_c1t_session.py"
RAW_FILENAME = "raw_measurements.jsonl"
BUNDLE_FILENAMES = (
    RAW_FILENAME,
    "session_manifest.json",
    "ground_truth_events.jsonl",
    "failure_events.jsonl",
    "deviation_events.jsonl",
    "checksums.sha256",
    "operator_notes.md",
)
RAW_FIELDS = (
    "co2_unit",
    "device_id_or_explicit_unknown",
    "device_uptime_ms",
    "ground_truth_label",
    "ground_truth_ref",
    "logger_monotonic_ns",
    "logger_timestamp_utc",
    "measurement_event_id",
    "missing_or_error_state",
    "pi_receive_monotonic_ns",
    "pi_receive_timestamp_utc",
    "protocol_id",
    "protocol_version",
    "raw_co2_ppm",
    "raw_received_payload",
    "raw_received_payload_text",
    "raw_record_number",
    "record_type",
    "sensor_event_id",
    "sensor_event_monotonic_ms",
    "sensor_event_valid",
    "sensor_measurement_freshness",
    "sensor_read_status",
    "session_id",
    "software_or_configuration_identity",
    "target_candidate_id",
    "telemetry_sequence",
    "transport_age_seconds",
    "transport_connected",
    "transport_freshness",
    "transport_status",
)


@dataclass(frozen=True)
class Snapshot:
    timestamp_utc: str
    logger_monotonic_ns: int
    pi_receive_monotonic_ns: int | None
    payload: dict[str, object] | None
    source_error: str | None


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def finite_number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(float(value)) else None


def event_identifier(value: object) -> str | int | float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an immutable SafeNest C-C1T CO2 session bundle.")
    parser.add_argument("--url", default="http://127.0.0.1:8080/health", help="Pi /health URL for live capture")
    parser.add_argument("--duration-sec", type=float, required=True)
    parser.add_argument("--interval-sec", type=float, default=1.0)
    parser.add_argument("--timeout-sec", type=float, default=3.0)
    parser.add_argument("--scenario", choices=("VACANT_STABLE", "OCCUPIED_STABLE"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--location-id", required=True)
    parser.add_argument("--fixture", type=Path, help="Deterministic JSONL source; never a physical measurement")
    # Explicit hard errors make prohibited requests unambiguous for callers.
    parser.add_argument("--forward-fill", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--interpolate", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--derive-ground-truth-from-co2", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--drop-error-rows", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--rewrite-raw", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.duration_sec <= 0 or args.interval_sec <= 0 or args.timeout_sec <= 0:
        parser.error("--duration-sec, --interval-sec, and --timeout-sec must be positive")
    forbidden = {
        "--forward-fill": args.forward_fill,
        "--interpolate": args.interpolate,
        "--derive-ground-truth-from-co2": args.derive_ground_truth_from_co2,
        "--drop-error-rows": args.drop_error_rows,
        "--rewrite-raw": args.rewrite_raw,
    }
    for option, requested in forbidden.items():
        if requested:
            parser.error(f"FORBIDDEN_OPERATION: {option}")
    return args


def fixture_snapshots(path: Path) -> Iterator[Snapshot]:
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"fixture JSONL line {line_number}: {exc}") from exc
            if not isinstance(item, dict) or not isinstance(item.get("captured_at_utc"), str):
                raise ValueError(f"fixture JSONL line {line_number}: captured_at_utc is required")
            payload = item.get("payload")
            if payload is not None and not isinstance(payload, dict):
                raise ValueError(f"fixture JSONL line {line_number}: payload must be object or null")
            monotonic = finite_number(item.get("logger_monotonic_ns"))
            if monotonic is None:
                raise ValueError(f"fixture JSONL line {line_number}: logger_monotonic_ns is required")
            source_error = item.get("source_error")
            if source_error is not None and not isinstance(source_error, str):
                raise ValueError(f"fixture JSONL line {line_number}: source_error must be string")
            yield Snapshot(item["captured_at_utc"], int(monotonic), None, payload, source_error)


def fetch_live_snapshot(url: str, timeout_sec: float) -> Snapshot:
    timestamp = iso_now()
    logger_monotonic_ns = time.monotonic_ns()
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return Snapshot(timestamp, logger_monotonic_ns, logger_monotonic_ns, None, "INVALID_HEALTH_JSON_ROOT")
        return Snapshot(timestamp, logger_monotonic_ns, logger_monotonic_ns, payload, None)
    except HTTPError as exc:
        return Snapshot(timestamp, logger_monotonic_ns, logger_monotonic_ns, None, f"HTTP_ERROR_{exc.code}")
    except URLError as exc:
        return Snapshot(timestamp, logger_monotonic_ns, logger_monotonic_ns, None, f"TRANSPORT_ERROR:{exc.reason}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Snapshot(timestamp, logger_monotonic_ns, logger_monotonic_ns, None, f"INVALID_HEALTH_JSON:{exc}")


def live_snapshots(url: str, duration_sec: float, interval_sec: float, timeout_sec: float) -> Iterator[Snapshot]:
    started = time.monotonic()
    deadline = started + duration_sec
    next_poll = started
    while time.monotonic() < deadline:
        yield fetch_live_snapshot(url, timeout_sec)
        next_poll += interval_sec
        remaining = next_poll - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)


def sensor_object(payload: dict[str, object] | None) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    sensors = payload.get("sensors")
    return sensors if isinstance(sensors, dict) else None


def sensor_or_transport(sensors: dict[str, object], payload: dict[str, object], key: str) -> object:
    if key in sensors:
        return sensors[key]
    transport = payload.get("transport")
    if isinstance(transport, dict) and key in transport:
        return transport[key]
    return None


def label_and_source(scenario: str) -> tuple[str, str]:
    if scenario == "VACANT_STABLE":
        return "VACANT", "CONTROLLED_EMPTY_ROOM"
    return "OCCUPIED", "CONTROLLED_PERSON_PRESENT"


def session_date(first_timestamp: str | None) -> str:
    if first_timestamp:
        return parse_utc(first_timestamp).strftime("%Y%m%d")
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def build_session_id(output_root: Path, operator_id: str, first_timestamp: str | None) -> str:
    operator_code = re.sub(r"[^A-Za-z0-9]", "", operator_id).upper() or "UNKNOWN"
    prefix = f"CO2C1R-{session_date(first_timestamp)}-{operator_code}-S"
    for sequence in range(1, 1000):
        candidate = f"{prefix}{sequence:03d}"
        if not (output_root / candidate).exists():
            return candidate
    raise RuntimeError("SESSION_ID_EXHAUSTED")


class BundleBuilder:
    def __init__(self, args: argparse.Namespace, session_id: str, mode: str) -> None:
        self.args = args
        self.session_id = session_id
        self.mode = mode
        self.label, self.ground_truth_source = label_and_source(args.scenario)
        self.raw_records: list[dict[str, object]] = []
        self.failures: list[dict[str, object]] = []
        self.deviations: list[dict[str, object]] = []
        self.fresh_events = 0
        self.cached_retransmissions = 0
        self.previous_event_by_device: dict[str, str] = {}
        self.last_numeric_event_by_device: dict[str, float] = {}

    def add_snapshot(self, snapshot: Snapshot) -> None:
        record_number = len(self.raw_records) + 1
        payload = snapshot.payload
        sensors = sensor_object(payload)
        raw_payload_text = canonical_json(payload) if payload is not None else None
        device_id = "EXPLICIT_UNKNOWN"
        event_id: str | int | float | None = None
        event_monotonic: int | float | None = None
        event_valid: bool | None = None
        transport_connected: bool | None = None
        transport_freshness = "UNKNOWN"
        transport_status = "UNKNOWN"
        transport_age: int | float | None = None
        telemetry_sequence: int | float | None = None
        device_uptime: int | float | None = None
        raw_co2: int | float | None = None
        missing_or_error: str | None = snapshot.source_error
        freshness = "MISSING_EVENT_MARKER"
        read_status = "TRANSPORT_FAILURE" if snapshot.source_error else "MISSING_SENSOR_EVENT_MARKER"

        if payload is not None and sensors is None:
            missing_or_error = "MISSING_SENSORS_OBJECT"
            read_status = "INVALID_PAYLOAD"
        elif sensors is not None and payload is not None:
            device_value = sensor_or_transport(sensors, payload, "device_id")
            if isinstance(device_value, str) and device_value:
                device_id = device_value
            event_id = event_identifier(sensors.get("co2_measurement_event_id"))
            event_monotonic = finite_number(sensors.get("co2_measurement_monotonic_ms"))
            valid_value = sensors.get("co2_measurement_event_valid")
            event_valid = valid_value if isinstance(valid_value, bool) else None
            raw_co2 = finite_number(sensors.get("co2_ppm"))
            transport_connected_value = sensor_or_transport(sensors, payload, "connected")
            transport_connected = transport_connected_value if isinstance(transport_connected_value, bool) else None
            fresh_value = sensor_or_transport(sensors, payload, "fresh")
            transport_freshness = "FRESH" if fresh_value is True else "NOT_FRESH" if fresh_value is False else "UNKNOWN"
            status_value = sensor_or_transport(sensors, payload, "status")
            transport_status = status_value if isinstance(status_value, str) and status_value else "UNKNOWN"
            transport_age = finite_number(sensor_or_transport(sensors, payload, "age_seconds"))
            telemetry_sequence = finite_number(sensor_or_transport(sensors, payload, "seq"))
            device_uptime = finite_number(sensor_or_transport(sensors, payload, "uptime_ms"))

            if event_id is None or event_monotonic is None or event_valid is None:
                missing_or_error = "MISSING_SENSOR_EVENT_MARKER"
                freshness = "MISSING_EVENT_MARKER"
                read_status = "MISSING_SENSOR_EVENT_MARKER"
            elif not event_valid:
                missing_or_error = "INVALID_SENSOR_EVENT_MARKER"
                freshness = "MISSING_EVENT_MARKER"
                read_status = "INVALID_SENSOR_EVENT_MARKER"
            else:
                event_key = str(event_id)
                previous = self.previous_event_by_device.get(device_id)
                if previous == event_key:
                    freshness = "CACHED_RETRANSMISSION"
                    read_status = "CACHED_LAST_SUCCESSFUL_READ"
                    self.cached_retransmissions += 1
                else:
                    freshness = "FRESH_EVENT"
                    read_status = "SUCCESSFUL_FRESH_READ"
                    self.fresh_events += 1
                    numeric_event = finite_number(event_id)
                    previous_numeric = self.last_numeric_event_by_device.get(device_id)
                    if numeric_event is not None and previous_numeric is not None and float(numeric_event) <= previous_numeric:
                        self.deviations.append(
                            {
                                "deviation_event_id": f"deviation-{len(self.deviations) + 1:04d}",
                                "device_id": device_id,
                                "event_id": event_id,
                                "previous_event_id": previous_numeric,
                                "reason": "NON_MONOTONIC_SENSOR_EVENT_ID",
                                "record_number": record_number,
                                "session_id": self.session_id,
                                "timestamp_utc": snapshot.timestamp_utc,
                            }
                        )
                    if numeric_event is not None:
                        self.last_numeric_event_by_device[device_id] = float(numeric_event)
                self.previous_event_by_device[device_id] = event_key

                valid_map = sensors.get("valid")
                co2_valid = isinstance(valid_map, dict) and valid_map.get("co2") is True
                if not co2_valid or raw_co2 is None:
                    missing_or_error = "CO2_VALID_FALSE_OR_VALUE_MISSING"

        if missing_or_error in {"MISSING_SENSOR_EVENT_MARKER", "INVALID_SENSOR_EVENT_MARKER"} or snapshot.source_error:
            self.failures.append(
                {
                    "failure_event_id": f"failure-{len(self.failures) + 1:04d}",
                    "failure_state": missing_or_error or "UNKNOWN_CAPTURE_FAILURE",
                    "raw_record_number": record_number,
                    "session_id": self.session_id,
                    "timestamp_utc": snapshot.timestamp_utc,
                }
            )

        record: dict[str, object] = {
            "co2_unit": "ppm",
            "device_id_or_explicit_unknown": device_id,
            "device_uptime_ms": device_uptime,
            "ground_truth_label": self.label,
            "ground_truth_ref": "gt-0001",
            "logger_monotonic_ns": snapshot.logger_monotonic_ns,
            "logger_timestamp_utc": snapshot.timestamp_utc,
            "measurement_event_id": f"{device_id}:{event_id}" if event_id is not None else None,
            "missing_or_error_state": missing_or_error,
            "pi_receive_monotonic_ns": snapshot.pi_receive_monotonic_ns,
            "pi_receive_timestamp_utc": snapshot.timestamp_utc if payload is not None else None,
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "raw_co2_ppm": raw_co2,
            "raw_received_payload": payload,
            "raw_received_payload_text": raw_payload_text,
            "raw_record_number": record_number,
            "record_type": "co2_acquisition_observation",
            "sensor_event_id": event_id,
            "sensor_event_monotonic_ms": event_monotonic,
            "sensor_event_valid": event_valid,
            "sensor_measurement_freshness": freshness,
            "sensor_read_status": read_status,
            "session_id": self.session_id,
            "software_or_configuration_identity": {
                "capture_script": SCRIPT_IDENTITY,
                "source_kind": "PI_HEALTH_HTTP",
                "team_telemetry_schema": "safenest.telemetry.v1",
            },
            "target_candidate_id": TARGET_CANDIDATE_ID,
            "telemetry_sequence": telemetry_sequence,
            "transport_age_seconds": transport_age,
            "transport_connected": transport_connected,
            "transport_freshness": transport_freshness,
            "transport_status": transport_status,
        }
        if set(record) != set(RAW_FIELDS):
            raise RuntimeError("RAW_RECORD_SCHEMA_INTERNAL_ERROR")
        self.raw_records.append(record)


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(canonical_json(record))
            stream.write("\n")


def write_text(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finalize_bundle(builder: BundleBuilder, output_root: Path, requested_duration: float) -> Path:
    if not builder.raw_records:
        raise RuntimeError("NO_RAW_RECORDS_CAPTURED")
    session_dir = output_root / builder.session_id
    session_dir.mkdir(parents=True, exist_ok=False)
    started = builder.raw_records[0]["logger_timestamp_utc"]
    ended = builder.raw_records[-1]["logger_timestamp_utc"]
    if builder.mode == "DRY_RUN_FIXTURE":
        duration = max(0.0, (parse_utc(str(ended)) - parse_utc(str(started))).total_seconds())
    else:
        duration = requested_duration
    ground_truth = {
        "derived_from_sensor_or_model": False,
        "end_or_transition_timestamp": ended,
        "ground_truth_event_id": "gt-0001",
        "ground_truth_status": "COMPLETE_STABLE_SEGMENT",
        "label": builder.label,
        "location_id": builder.args.location_id,
        "operator_id": builder.args.operator_id,
        "scenario_id": builder.args.scenario,
        "session_id": builder.session_id,
        "source": builder.ground_truth_source,
        "start_timestamp": started,
    }
    if ground_truth["derived_from_sensor_or_model"] is not False:
        raise RuntimeError("GROUND_TRUTH_MUST_BE_INDEPENDENT")

    write_jsonl(session_dir / RAW_FILENAME, builder.raw_records)
    write_jsonl(session_dir / "ground_truth_events.jsonl", [ground_truth])
    write_jsonl(session_dir / "failure_events.jsonl", builder.failures)
    write_jsonl(session_dir / "deviation_events.jsonl", builder.deviations)

    physical_claim = (
        "NOT_CLAIMED_FOR_DRY_RUN"
        if builder.mode == "DRY_RUN_FIXTURE"
        else "EXPLORATORY_REAL_DEVICE_CAPTURE_ONLY_FORMAL_CLAIMS_BLOCKED"
    )
    manifest_note = (
        "Deterministic C-C1T protocol fixture; not physical sensor validation."
        if builder.mode == "DRY_RUN_FIXTURE"
        else "Raw capture finalized without interpolation, model inference, or preprocessing."
    )
    manifest = {
        "candidate_lock_content_sha256": CANDIDATE_LOCK_CONTENT_SHA256,
        "candidate_lock_sha256": CANDIDATE_LOCK_SHA256,
        "capture_configuration": {
            "configured_capture_poll_interval_sec": builder.args.interval_sec,
            "effective_model_input_cadence": "NOMINAL",
            "effective_model_input_interval_sec": 60,
            "native_sensor_cadence_separate": True,
            "requested_duration_sec": builder.args.duration_sec,
            "source_endpoint_label": builder.args.url,
            "source_kind": "PI_HEALTH_HTTP",
        },
        "capture_duration_sec": duration,
        "capture_end_timestamp_utc": ended,
        "capture_mode": builder.mode,
        "capture_software": {
            "language": "Python standard library",
            "model_inference_performed": False,
            "preprocessing_performed": False,
            "script": SCRIPT_IDENTITY,
        },
        "capture_start_timestamp_utc": started,
        "counts": {
            "cached_retransmissions": builder.cached_retransmissions,
            "deviation_events": len(builder.deviations),
            "failure_events": len(builder.failures),
            "fresh_events": builder.fresh_events,
            "ground_truth_events": 1,
            "raw_records": len(builder.raw_records),
        },
        "device_identity": "RECORDED_PER_ROW_OR_UNKNOWN",
        "evidence_class": EVIDENCE_CLASS,
        "feature_order": ["CO2", "CO2_slope"],
        "files": {filename: filename for filename in BUNDLE_FILENAMES},
        "freshness_contract_applied": {
            "missing_event_recording": True,
            "same_event_id_is_cached_retransmission": True,
            "stale_reuse": False,
            "synthetic_fill": False,
            "transport_freshness_is_sensor_freshness": False,
        },
        "location_id": builder.args.location_id,
        "manifest_version": "1.0",
        "measurement_protocol_id": PROTOCOL_ID,
        "measurement_protocol_version": PROTOCOL_VERSION,
        "operator_id": builder.args.operator_id,
        "operator_notes": manifest_note,
        "phase": "C-C1T",
        "physical_measurement_claim": physical_claim,
        "scenario_id": builder.args.scenario,
        "session_id": builder.session_id,
        "session_status": "FINALIZED",
        "target_candidate_id": TARGET_CANDIDATE_ID,
    }
    write_text(session_dir / "session_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    notes = (
        "Deterministic C-C1T protocol fixture; not physical sensor validation."
        if builder.mode == "DRY_RUN_FIXTURE"
        else "Add factual environment, interruption, reconnection, and transition observations without editing raw rows."
    )
    write_text(
        session_dir / "operator_notes.md",
        "# Operator notes\n\n"
        f"- session_id: `{builder.session_id}`\n"
        f"- capture_mode: `{builder.mode}`\n"
        f"- physical_measurement_claim: `{physical_claim}`\n"
        f"- notes: {notes}\n\n"
        "This file is finalized with the session bundle. Do not edit prior rows.\n",
    )

    hash_order = (
        "deviation_events.jsonl",
        "failure_events.jsonl",
        "ground_truth_events.jsonl",
        "operator_notes.md",
        RAW_FILENAME,
        "session_manifest.json",
    )
    checksums = "".join(f"{sha256_file(session_dir / name)}  {name}\n" for name in hash_order)
    write_text(session_dir / "checksums.sha256", checksums)
    return session_dir


def run_capture(args: argparse.Namespace) -> Path:
    mode = "DRY_RUN_FIXTURE" if args.fixture else "LIVE_PI_HEALTH"
    snapshots = list(fixture_snapshots(args.fixture)) if args.fixture else list(
        live_snapshots(args.url, args.duration_sec, args.interval_sec, args.timeout_sec)
    )
    first_timestamp = snapshots[0].timestamp_utc if snapshots else None
    session_id = build_session_id(args.output_dir, args.operator_id, first_timestamp)
    builder = BundleBuilder(args, session_id, mode)
    for snapshot in snapshots:
        builder.add_snapshot(snapshot)
    return finalize_bundle(builder, args.output_dir, args.duration_sec)


def main() -> None:
    args = parse_args()
    session_dir = run_capture(args)
    print(f"session_id={session_dir.name} path={session_dir}")


if __name__ == "__main__":
    main()
