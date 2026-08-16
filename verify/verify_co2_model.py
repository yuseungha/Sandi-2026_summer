#!/usr/bin/env python3
"""Offline C-B6 contract checker; it never substitutes the legacy 3-input model.

The tool may read a finished raw JSONL/CSV bundle without hardware. Slope is a
Pi/downstream-only derived artifact, never written back into raw evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
CONTRACT_DIR = ROOT / "contracts"
DEFAULT_MODEL = ROOT.parent / "models" / "co2" / "candidates" / "c_b6" / "full_integer_int8.tflite"
EXPECTED_FEATURE_ORDER = ["CO2", "CO2_slope"]
LEGACY_TEAM_FEATURE_ORDER = ["CO2_slope", "Humidity", "CO2"]
THRESHOLD = 0.43
HISTORY_SEC = 150.0
GAP_RESET_SEC = 90.0


@dataclass(frozen=True)
class FreshPoint:
    timestamp: float
    co2_ppm: float
    event_id: str


@dataclass(frozen=True)
class SlopeResult:
    point: FreshPoint
    slope_ppm_per_min: float | None
    status: str
    history_span_sec: float | None


def load_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def parse_timestamp(value: object) -> float:
    if not isinstance(value, str):
        raise ValueError("timestamp is missing")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def raw_rows(path: Path) -> Iterable[dict[str, object]]:
    if path.is_dir():
        path = path / "raw_measurements.jsonl"
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as stream:
            yield from csv.DictReader(stream)
        return
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL row {line_number} is not an object")
            yield value


def verified_fresh_points(rows: Iterable[dict[str, object]]) -> tuple[list[FreshPoint], int]:
    points: list[FreshPoint] = []
    rejected = 0
    for row in rows:
        if row.get("sensor_measurement_freshness") != "FRESH_EVENT":
            rejected += 1
            continue
        co2 = number(row.get("raw_co2_ppm", row.get("co2_ppm")))
        event = row.get("measurement_event_id", row.get("sensor_event_id"))
        timestamp = row.get("logger_timestamp_utc", row.get("host_timestamp"))
        if co2 is None or event is None:
            rejected += 1
            continue
        try:
            points.append(FreshPoint(parse_timestamp(timestamp), co2, str(event)))
        except ValueError:
            rejected += 1
    points.sort(key=lambda point: point.timestamp)
    return points, rejected


def endpoint_h150(points: Iterable[FreshPoint]) -> list[SlopeResult]:
    """Use the earliest same-block event at least 150 seconds in the past.

    There is no interpolation, duplication, or forward-fill. Any verified-fresh
    inter-event gap over 90 seconds drops the prior history before this point.
    """
    history: list[FreshPoint] = []
    results: list[SlopeResult] = []
    previous: FreshPoint | None = None
    for point in points:
        reset = previous is not None and point.timestamp - previous.timestamp > GAP_RESET_SEC
        if reset:
            history = []
        history.append(point)
        candidates = [candidate for candidate in history[:-1] if point.timestamp - candidate.timestamp >= HISTORY_SEC]
        if candidates:
            endpoint = candidates[0]
            elapsed = point.timestamp - endpoint.timestamp
            results.append(SlopeResult(point, (point.co2_ppm - endpoint.co2_ppm) / elapsed * 60.0, "AVAILABLE", elapsed))
        else:
            results.append(SlopeResult(point, None, "FEATURE_UNAVAILABLE_GAP_RESTART" if reset else "FEATURE_UNAVAILABLE_WARMUP", None))
        previous = point
    return results


def print_contract_summary() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    input_contract = load_json(CONTRACT_DIR / "c_b6_input_contract.json")
    scaler = load_json(CONTRACT_DIR / "c_b6_scaler_metadata.json")
    tflite_contract = load_json(CONTRACT_DIR / "c_b6_tflite_contract.json")
    print("ACTIVE_INPUT_CONTRACT=C_B6_REDUCED_2_FEATURE")
    print("FEATURE_ORDER=" + json.dumps(EXPECTED_FEATURE_ORDER))
    print(f"THRESHOLD={THRESHOLD}")
    print(f"SLOPE=ENDPOINT_H150 history_sec={HISTORY_SEC:g} gap_reset_sec={GAP_RESET_SEC:g}")
    if input_contract.get("feature_order") != EXPECTED_FEATURE_ORDER or scaler.get("feature_order") != EXPECTED_FEATURE_ORDER:
        raise ValueError("C_B6_CONTRACT_METADATA_MISMATCH")
    return input_contract, scaler, tflite_contract


def print_slope_summary(results: list[SlopeResult], rejected: int) -> None:
    available = [item for item in results if item.slope_ppm_per_min is not None]
    resets = sum(item.status == "FEATURE_UNAVAILABLE_GAP_RESTART" for item in results)
    print(f"VERIFIED_FRESH_EVENT_COUNT={len(results)}")
    print(f"NON_ELIGIBLE_OR_REJECTED_ROW_COUNT={rejected}")
    print(f"H150_AVAILABLE_COUNT={len(available)}")
    print(f"H150_GAP_RESET_COUNT={resets}")
    if available:
        print(f"H150_LAST_SLOPE_PPM_PER_MIN={available[-1].slope_ppm_per_min:.9f}")
    else:
        print("H150_LAST_SLOPE_PPM_PER_MIN=UNAVAILABLE")


def tflite_interpreter():
    try:
        from ai_edge_litert.interpreter import Interpreter  # type: ignore
        return Interpreter
    except ImportError:
        try:
            from tflite_runtime.interpreter import Interpreter  # type: ignore
            return Interpreter
        except ImportError:
            try:
                from tensorflow.lite import Interpreter  # type: ignore
                return Interpreter
            except ImportError as exc:
                raise RuntimeError("TFLITE_RUNTIME_UNAVAILABLE") from exc


def print_tensor_table(input_detail: dict[str, object], output_detail: dict[str, object]) -> None:
    print("| tensor | shape | dtype | scale | zero_point |")
    print("|---|---|---|---:|---:|")
    for name, detail in (("input", input_detail), ("output", output_detail)):
        quant = detail.get("quantization", (0.0, 0))
        scale, zero_point = quant if isinstance(quant, tuple) else (0.0, 0)
        shape = [int(value) for value in detail["shape"]]
        dtype = getattr(detail["dtype"], "__name__", str(detail["dtype"]))
        print(f"| {name} | {shape} | {dtype} | {float(scale):.12g} | {int(zero_point)} |")


def validate_tensors(interpreter: object, tflite_contract: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    interpreter.allocate_tensors()
    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]
    print_tensor_table(input_detail, output_detail)
    expected = tflite_contract["int8_tflite"]
    expected_shape = expected["input_shape"]
    actual_shape = [int(value) for value in input_detail["shape"]]
    actual_dtype = getattr(input_detail["dtype"], "__name__", str(input_detail["dtype"]))
    if actual_shape != expected_shape or actual_dtype != expected["input_dtype"]:
        print("MODEL_INPUT_CONTRACT_MISMATCH")
        print("EXPECTED=" + json.dumps(EXPECTED_FEATURE_ORDER))
        print(f"ACTUAL_SHAPE={actual_shape} ACTUAL_DTYPE={actual_dtype}")
        raise ValueError("MODEL_INPUT_CONTRACT_MISMATCH")
    return input_detail, output_detail


def saturation_report(results: list[SlopeResult], scaler: dict[str, object], input_scale: float, input_zero_point: int) -> None:
    means = scaler["mean"]
    scales = scaler["scale"]
    lower = upper = 0
    usable = 0
    for item in results:
        if item.slope_ppm_per_min is None:
            continue
        standardized_slope = (item.slope_ppm_per_min - float(means[1])) / float(scales[1])
        unbounded = round(standardized_slope / input_scale + input_zero_point)
        usable += 1
        lower += int(unbounded < -128)
        upper += int(unbounded > 127)
    print(f"INT8_SLOPE_SATURATION_INPUTS={usable}")
    print(f"INT8_SLOPE_SATURATION_LOWER_COUNT={lower}")
    print(f"INT8_SLOPE_SATURATION_UPPER_COUNT={upper}")
    print("INT8_SLOPE_SATURATION_OFFLINE_REFERENCE=train:12 validation:3")


def verify_determinism(interpreter: object, input_detail: dict[str, object], output_detail: dict[str, object], results: list[SlopeResult], scaler: dict[str, object]) -> None:
    available = next((item for item in results if item.slope_ppm_per_min is not None), None)
    if available is None:
        print("DETERMINISM=NOT_RUN_NO_H150_ELIGIBLE_INPUT")
        return
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("NUMPY_REQUIRED_BY_TFLITE_RUNTIME") from exc
    mean = np.asarray(scaler["mean"], dtype=np.float32)
    scale = np.asarray(scaler["scale"], dtype=np.float32)
    features = np.asarray([available.point.co2_ppm, available.slope_ppm_per_min], dtype=np.float32)
    standardized = (features - mean) / scale
    dtype = input_detail["dtype"]
    quant_scale, quant_zero = input_detail["quantization"]
    if np.issubdtype(dtype, np.integer):
        prepared = np.clip(np.rint(standardized / quant_scale + quant_zero), -128, 127).astype(dtype).reshape(1, 2)
    else:
        prepared = standardized.astype(dtype).reshape(1, 2)
    output_bytes: list[bytes] = []
    for _ in range(2):
        interpreter.set_tensor(input_detail["index"], prepared)
        interpreter.invoke()
        output_bytes.append(interpreter.get_tensor(output_detail["index"]).tobytes())
    print("DETERMINISM=BITWISE_IDENTICAL" if output_bytes[0] == output_bytes[1] else "DETERMINISM=FAILED")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify C-B6 CO2 model contract without physical hardware.")
    parser.add_argument("--session-dir", type=Path, required=True, help="Bundle directory, JSONL, or CSV")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--model-contract", choices=("c_b6", "team_legacy_3feature"), default="c_b6")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _input_contract, scaler, tflite_contract = print_contract_summary()
    if args.model_contract == "team_legacy_3feature":
        print("REQUESTED_INPUT_CONTRACT=TEAM_LEGACY_3_FEATURE")
        print("TEAM_LEGACY_FEATURE_ORDER=" + json.dumps(LEGACY_TEAM_FEATURE_ORDER))
        print("MODEL_INPUT_CONTRACT_MISMATCH")
        print("REFUSED: C_B6 requires [CO2, CO2_slope]; legacy CO2Interpreter.predict(co2_slope, humidity, co2_ppm) is not interchangeable.")
        return 3

    points, rejected = verified_fresh_points(raw_rows(args.session_dir))
    results = endpoint_h150(points)
    print_slope_summary(results, rejected)
    expected_quant = tflite_contract["int8_tflite"]["input_quantization"]
    saturation_report(results, scaler, float(expected_quant["scale"]), int(expected_quant["zero_point"]))

    if not args.model_path.is_file():
        print(f"MODEL_ARTIFACT_UNAVAILABLE path={args.model_path}")
        print("No substitute model was loaded; obtain the locked C_B6 TFLite binary and verify its SHA-256 before rerunning.")
        return 2
    try:
        Interpreter = tflite_interpreter()
        interpreter = Interpreter(model_path=str(args.model_path))
        input_detail, output_detail = validate_tensors(interpreter, tflite_contract)
        verify_determinism(interpreter, input_detail, output_detail, results, scaler)
    except ValueError as exc:
        print(str(exc))
        return 3
    except RuntimeError as exc:
        print(str(exc))
        return 4
    print("MODEL_CONTRACT=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
