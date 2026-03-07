import os
from typing import Any

from app.sensors.base import Sensor


class CpuLoadSensor(Sensor):
    id = "cpu_load"
    _LOAD_PRECISION = 2

    def collect(self) -> dict[str, Any]:
        load1, load5, load15 = os.getloadavg()
        return {
            "load_1": round(load1, self._LOAD_PRECISION),
            "load_5": round(load5, self._LOAD_PRECISION),
            "load_15": round(load15, self._LOAD_PRECISION),
            "cpu_count": os.cpu_count(),
        }
