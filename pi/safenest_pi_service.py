#!/usr/bin/env python3
"""SafeNest v1 CO2 receiver with an event-field preserving /health endpoint.

This service is a pass-through boundary: it stores the latest sender `sensors`
object and adds transport state only when responding to `/health`. It never
creates, increments, repairs, or copies a SCD40 measurement-event field.
"""

from __future__ import annotations

import argparse
import copy
import json
import socket
import struct
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SENSOR_MAGIC = b"SNST"
SENSOR_PROTOCOL_VERSION = 1
PACKET_TELEMETRY_JSON = 1
PACKET_HEADER = struct.Struct("!4sBBHII")
MAX_SENSOR_PAYLOAD_BYTES = 20_000
EXPECTED_TELEMETRY_SCHEMA = "safenest.telemetry.v1"
EVENT_FIELDS = (
    "co2_measurement_event_id",
    "co2_measurement_monotonic_ms",
    "co2_measurement_event_valid",
)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class SensorStore:
    """Thread-safe latest telemetry store; event fields are retained verbatim."""

    def __init__(self, stale_seconds: float) -> None:
        self.stale_seconds = stale_seconds
        self._lock = threading.Lock()
        self._sensors: dict[str, object] = {}
        self._device: dict[str, object] = {}
        self._connected = False
        self._peer: str | None = None
        self._last_received_monotonic: float | None = None
        self._last_received_at: int | None = None
        self._listener_error: str | None = None

    def set_listener_error(self, error: str | None) -> None:
        with self._lock:
            self._listener_error = error

    def set_connected(self, connected: bool, peer: tuple[str, int] | None = None) -> None:
        with self._lock:
            self._connected = connected
            self._peer = f"{peer[0]}:{peer[1]}" if connected and peer else None

    def record_telemetry(self, payload: dict[str, object]) -> None:
        if payload.get("schema") != EXPECTED_TELEMETRY_SCHEMA:
            raise ValueError(f"unsupported telemetry schema: {payload.get('schema')!r}")
        sensors = payload.get("sensors")
        if not isinstance(sensors, dict):
            raise ValueError("telemetry sensors must be an object")

        # deepcopy is preservation, not normalisation: missing fields stay missing
        # and values retain their JSON type and value exactly as sent by ESP32.
        with self._lock:
            self._sensors = copy.deepcopy(sensors)
            self._device = {
                key: copy.deepcopy(payload[key])
                for key in ("schema", "device_id", "seq", "uptime_ms")
                if key in payload
            }
            self._last_received_monotonic = time.monotonic()
            self._last_received_at = int(time.time())
            self._listener_error = None

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            age = None
            if self._last_received_monotonic is not None:
                age = max(0.0, time.monotonic() - self._last_received_monotonic)
            fresh = bool(self._connected and age is not None and age <= self.stale_seconds)
            if self._listener_error:
                status = "error"
            elif fresh:
                status = "live"
            elif self._last_received_at is not None:
                status = "stale"
            else:
                status = "waiting"

            sensors = copy.deepcopy(self._sensors)
            # These are transport fields. Never add or modify EVENT_FIELDS here.
            sensors.update(
                {
                    "connected": self._connected,
                    "fresh": fresh,
                    "status": status,
                    "peer": self._peer,
                    "age_seconds": round(age, 3) if age is not None else None,
                    "last_received_at": self._last_received_at,
                }
            )
            return {
                "server": "safenest-pi",
                "sensors": {**self._device, **sensors},
                "listener_error": self._listener_error,
            }


def recv_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        part = connection.recv(remaining)
        if not part:
            raise ConnectionError("ESP32 closed the TCP connection")
        chunks.append(part)
        remaining -= len(part)
    return b"".join(chunks)


class SensorReceiver:
    def __init__(self, host: str, port: int, store: SensorStore) -> None:
        self.host = host
        self.port = port
        self.store = store
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="safenest-co2-receiver", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=3)

    def _handle_connection(self, connection: socket.socket, peer: tuple[str, int]) -> None:
        self.store.set_connected(True, peer)
        connection.settimeout(1.0)
        try:
            while not self.stop_event.is_set():
                try:
                    header = recv_exact(connection, PACKET_HEADER.size)
                except socket.timeout:
                    continue
                magic, version, packet_type, flags, _sequence, length = PACKET_HEADER.unpack(header)
                if magic != SENSOR_MAGIC or version != SENSOR_PROTOCOL_VERSION or flags != 0:
                    raise ValueError("invalid SafeNest v1 header")
                if length > MAX_SENSOR_PAYLOAD_BYTES:
                    raise ValueError(f"payload too large: {length}")
                body = recv_exact(connection, length)
                if packet_type != PACKET_TELEMETRY_JSON:
                    continue
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("telemetry root is not an object")
                self.store.record_telemetry(payload)
        finally:
            self.store.set_connected(False)

    def _run(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((self.host, self.port))
                listener.listen(2)
                listener.settimeout(1.0)
                self.store.set_listener_error(None)
                print(f"[PI_LISTENING] {self.host}:{self.port}")
                while not self.stop_event.is_set():
                    try:
                        connection, peer = listener.accept()
                    except socket.timeout:
                        continue
                    print(f"[PI_CONNECTED] {peer[0]}:{peer[1]}")
                    with connection:
                        try:
                            self._handle_connection(connection, peer)
                        except (ConnectionError, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                            if not self.stop_event.is_set():
                                self.store.set_listener_error(str(exc))
                                print(f"[PI_RECEIVE_ERROR] {exc}")
        except OSError as exc:
            self.store.set_listener_error(str(exc))
            print(f"[PI_LISTENER_ERROR] {exc}")


def make_handler(store: SensorStore) -> type[BaseHTTPRequestHandler]:
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/health":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = canonical_json(store.snapshot())
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return HealthHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SafeNest CO2 TCP receiver and /health service")
    parser.add_argument("--sensor-host", default="0.0.0.0")
    parser.add_argument("--sensor-port", type=int, default=9000)
    parser.add_argument("--http-host", default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=8080)
    parser.add_argument("--sensor-stale-sec", type=float, default=15.0)
    args = parser.parse_args()
    if args.sensor_port <= 0 or args.http_port <= 0 or args.sensor_stale_sec <= 0:
        parser.error("ports and --sensor-stale-sec must be positive")
    return args


def main() -> None:
    args = parse_args()
    store = SensorStore(args.sensor_stale_sec)
    receiver = SensorReceiver(args.sensor_host, args.sensor_port, store)
    receiver.start()
    server = ThreadingHTTPServer((args.http_host, args.http_port), make_handler(store))
    print(f"[PI_HEALTH] http://{args.http_host}:{args.http_port}/health")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("[PI_STOP] requested")
    finally:
        server.shutdown()
        receiver.stop()


if __name__ == "__main__":
    main()
