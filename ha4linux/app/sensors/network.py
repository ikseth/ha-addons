import time
from fnmatch import fnmatchcase
from typing import Any

from app.sensors.base import Sensor


class NetworkSensor(Sensor):
    id = "network"
    _BYTES_PER_KIB = 1024
    _WINDOW_PRECISION = 2

    def __init__(
        self,
        *,
        include_interfaces: list[str] | None = None,
        exclude_interfaces: list[str] | None = None,
        aggregate_mode: str = "selected",
    ) -> None:
        self._include_interfaces = [item for item in (include_interfaces or []) if item]
        self._exclude_interfaces = [item for item in (exclude_interfaces or []) if item]
        self._aggregate_mode = aggregate_mode if aggregate_mode in {"selected", "all"} else "selected"
        self._last_interface_totals: dict[str, tuple[int, int]] = {}
        self._last_aggregate_totals: tuple[int, int] | None = None
        self._last_sample_ts: float | None = None

    def collect(self) -> dict[str, Any]:
        discovered_interfaces: dict[str, dict[str, int]] = {}

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

            discovered_interfaces[name] = {
                "rx_bytes": rx_bytes,
                "tx_bytes": tx_bytes,
            }

        available_interfaces = self._filter_interfaces(
            discovered_interfaces,
            include_patterns=self._exclude_interfaces,
            negate=True,
        )
        selected_interfaces = self._filter_interfaces(
            available_interfaces,
            include_patterns=self._include_interfaces,
            negate=False,
        )
        aggregate_interfaces = (
            available_interfaces if self._aggregate_mode == "all" else selected_interfaces
        )
        totals_rx = sum(item["rx_bytes"] for item in aggregate_interfaces.values())
        totals_tx = sum(item["tx_bytes"] for item in aggregate_interfaces.values())

        now_ts = time.monotonic()
        delta_rx = 0
        delta_tx = 0
        window_seconds = 0.0

        if self._last_aggregate_totals is not None and self._last_sample_ts is not None:
            prev_rx, prev_tx = self._last_aggregate_totals
            raw_delta_rx = totals_rx - prev_rx
            raw_delta_tx = totals_tx - prev_tx

            # If counters reset (reboot/interface reset), keep the sample usable.
            delta_rx = raw_delta_rx if raw_delta_rx >= 0 else totals_rx
            delta_tx = raw_delta_tx if raw_delta_tx >= 0 else totals_tx
            window_seconds = max(now_ts - self._last_sample_ts, 0.0)

        interfaces: dict[str, dict[str, int | float]] = {}
        for name, counters in selected_interfaces.items():
            rx_bytes = counters["rx_bytes"]
            tx_bytes = counters["tx_bytes"]
            prev_totals = self._last_interface_totals.get(name)
            iface_delta_rx = 0
            iface_delta_tx = 0

            if prev_totals is not None and self._last_sample_ts is not None:
                prev_rx, prev_tx = prev_totals
                raw_delta_rx = rx_bytes - prev_rx
                raw_delta_tx = tx_bytes - prev_tx
                iface_delta_rx = raw_delta_rx if raw_delta_rx >= 0 else rx_bytes
                iface_delta_tx = raw_delta_tx if raw_delta_tx >= 0 else tx_bytes

            interfaces[name] = {
                "rx_bytes": rx_bytes,
                "tx_bytes": tx_bytes,
                "rx_kib_window": round(iface_delta_rx / self._BYTES_PER_KIB, self._WINDOW_PRECISION),
                "tx_kib_window": round(iface_delta_tx / self._BYTES_PER_KIB, self._WINDOW_PRECISION),
            }

        self._last_interface_totals = {
            name: (item["rx_bytes"], item["tx_bytes"])
            for name, item in selected_interfaces.items()
        }
        self._last_aggregate_totals = (totals_rx, totals_tx)
        self._last_sample_ts = now_ts

        return {
            "total_rx_bytes": totals_rx,
            "total_tx_bytes": totals_tx,
            "rx_kib_window": round(delta_rx / self._BYTES_PER_KIB, self._WINDOW_PRECISION),
            "tx_kib_window": round(delta_tx / self._BYTES_PER_KIB, self._WINDOW_PRECISION),
            "window_seconds": round(window_seconds, 3),
            "aggregate_mode": self._aggregate_mode,
            "selected_interfaces": sorted(selected_interfaces.keys()),
            "interfaces": interfaces,
        }

    @staticmethod
    def _matches_patterns(interface_name: str, patterns: list[str]) -> bool:
        return any(fnmatchcase(interface_name, pattern) for pattern in patterns)

    def _filter_interfaces(
        self,
        interfaces: dict[str, dict[str, int]],
        *,
        include_patterns: list[str],
        negate: bool,
    ) -> dict[str, dict[str, int]]:
        if not include_patterns:
            return dict(interfaces)

        filtered: dict[str, dict[str, int]] = {}
        for name, counters in interfaces.items():
            matches = self._matches_patterns(name, include_patterns)
            if negate:
                if not matches:
                    filtered[name] = counters
                continue
            if matches:
                filtered[name] = counters
        return filtered
