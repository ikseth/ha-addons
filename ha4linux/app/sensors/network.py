import time
from typing import Any

from app.sensors.base import Sensor


class NetworkSensor(Sensor):
    id = "network"
    _BYTES_PER_KIB = 1024
    _WINDOW_PRECISION = 2

    def __init__(self) -> None:
        self._last_totals: tuple[int, int] | None = None
        self._last_sample_ts: float | None = None

    def collect(self) -> dict[str, Any]:
        interfaces: dict[str, dict[str, int]] = {}
        totals_rx = 0
        totals_tx = 0

        with open("/proc/net/dev", "r", encoding="utf-8") as handle:
            lines = handle.readlines()[2:]

        for line in lines:
            name_raw, data_raw = line.split(":", 1)
            name = name_raw.strip()
            if not name or name == "lo":
                continue

            fields = data_raw.split()
            rx_bytes = int(fields[0])
            tx_bytes = int(fields[8])

            interfaces[name] = {
                "rx_bytes": rx_bytes,
                "tx_bytes": tx_bytes,
            }
            totals_rx += rx_bytes
            totals_tx += tx_bytes

        now_ts = time.monotonic()
        delta_rx = 0
        delta_tx = 0
        window_seconds = 0.0

        if self._last_totals is not None and self._last_sample_ts is not None:
            prev_rx, prev_tx = self._last_totals
            raw_delta_rx = totals_rx - prev_rx
            raw_delta_tx = totals_tx - prev_tx

            # If counters reset (reboot/interface reset), keep the sample usable.
            delta_rx = raw_delta_rx if raw_delta_rx >= 0 else totals_rx
            delta_tx = raw_delta_tx if raw_delta_tx >= 0 else totals_tx
            window_seconds = max(now_ts - self._last_sample_ts, 0.0)

        self._last_totals = (totals_rx, totals_tx)
        self._last_sample_ts = now_ts

        return {
            "total_rx_bytes": totals_rx,
            "total_tx_bytes": totals_tx,
            "rx_kib_window": round(delta_rx / self._BYTES_PER_KIB, self._WINDOW_PRECISION),
            "tx_kib_window": round(delta_tx / self._BYTES_PER_KIB, self._WINDOW_PRECISION),
            "window_seconds": round(window_seconds, 3),
            "interfaces": interfaces,
        }
