from app.sensors.base import Sensor


class NetworkSensor(Sensor):
    id = "network"

    def collect(self) -> dict[str, object]:
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

        return {
            "total_rx_bytes": totals_rx,
            "total_tx_bytes": totals_tx,
            "interfaces": interfaces,
        }
