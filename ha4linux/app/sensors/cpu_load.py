import os
from typing import Any

from app.sensors.base import Sensor


class CpuLoadSensor(Sensor):
    id = "cpu_load"

    def collect(self) -> dict[str, Any]:
        load1, load5, load15 = os.getloadavg()
        return {
            "load_1": load1,
            "load_5": load5,
            "load_15": load15,
            "cpu_count": os.cpu_count(),
        }
