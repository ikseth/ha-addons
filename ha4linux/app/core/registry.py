from typing import Any

from app.actuators.base import Actuator
from app.actuators.session_manager import SessionManagerActuator
from app.core.config import Settings
from app.sensors.base import Sensor
from app.sensors.cpu_load import CpuLoadSensor
from app.sensors.memory import MemorySensor
from app.sensors.network import NetworkSensor


class ModuleRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sensors: dict[str, Sensor] = {}
        self.actuators: dict[str, Actuator] = {}

    def load(self) -> None:
        if self.settings.sensors_cpu:
            self.sensors[CpuLoadSensor.id] = CpuLoadSensor()

        if self.settings.sensors_memory:
            self.sensors[MemorySensor.id] = MemorySensor()

        if self.settings.sensors_network:
            self.sensors[NetworkSensor.id] = NetworkSensor()

        if self.settings.actuator_session:
            self.actuators[SessionManagerActuator.id] = SessionManagerActuator(
                allowed_users=self.settings.allowed_session_users,
            )

    def collect_sensors(self) -> dict[str, dict[str, Any]]:
        data: dict[str, dict[str, Any]] = {}
        for sensor_id, sensor in self.sensors.items():
            try:
                data[sensor_id] = {
                    "enabled": True,
                    "available": True,
                    "data": sensor.collect(),
                }
            except Exception as exc:  # Keep API alive if a sensor fails
                data[sensor_id] = {
                    "enabled": True,
                    "available": False,
                    "reason": str(exc),
                }
        return data

    def execute_actuator(
        self,
        actuator_id: str,
        action: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        actuator = self.actuators.get(actuator_id)
        if actuator is None:
            return {
                "ok": False,
                "error": f"Actuator '{actuator_id}' not available or disabled",
            }

        try:
            return actuator.execute(action=action, params=params)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
