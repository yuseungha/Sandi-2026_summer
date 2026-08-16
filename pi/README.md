# Pi receiver and health service

Run this CO2-only service only after the operator has verified that ports 9000 and 8080 are free on the intended Pi:

```bash
python3 pi/safenest_pi_service.py --sensor-port 9000 --http-port 8080
curl -sS http://127.0.0.1:8080/health
```

`/health.sensors.co2_measurement_event_id`, `co2_measurement_monotonic_ms`, and `co2_measurement_event_valid` are copied from the latest accepted ESP32 payload. If they are absent, they remain absent; the Pi does not manufacture an event marker. `fresh` and `status` describe receiver transport state only.
