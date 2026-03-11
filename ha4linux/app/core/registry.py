import logging
from pathlib import Path
from typing import Any

from app.actuators.app_policy import AppPolicyActuator
from app.actuators.base import Actuator
from app.actuators.session_manager import SessionManagerActuator
from app.core.app_policy_manager import AppPolicyManager
from app.core.config import Settings
from app.sensors.app_policies import AppPoliciesSensor
from app.sensors.base import Sensor
from app.sensors.cpu_load import CpuLoadSensor
from app.sensors.memory import MemorySensor
from app.sensors.network import NetworkSensor
from app.sensors.raid_mdstat import RaidMdstatSensor
from app.sensors.services import ServicesSensor
from app.sensors.virtualbox import VirtualBoxSensor

LOGGER = logging.getLogger(__name__)


class ModuleRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sensors: dict[str, Sensor] = {}
        self.actuators: dict[str, Actuator] = {}
        self.app_policy_manager: AppPolicyManager | None = None

    def load(self) -> None:
        if self.settings.sensors_cpu:
            self.sensors[CpuLoadSensor.id] = CpuLoadSensor()

        if self.settings.sensors_memory:
            self.sensors[MemorySensor.id] = MemorySensor()

        if self.settings.sensors_network:
            self.sensors[NetworkSensor.id] = NetworkSensor()

        if self.settings.sensors_raid:
            if Path("/proc/mdstat").exists():
                self.sensors[RaidMdstatSensor.id] = RaidMdstatSensor()
            else:
                LOGGER.info("Skipping sensor '%s': /proc/mdstat not found", RaidMdstatSensor.id)

        if self.settings.sensors_virtualbox:
            virtualbox_sensor = self._build_virtualbox_sensor()
            if virtualbox_sensor is not None:
                self.sensors[VirtualBoxSensor.id] = virtualbox_sensor

        if self.settings.sensors_services:
            services_sensor = self._build_services_sensor()
            if services_sensor is not None:
                self.sensors[ServicesSensor.id] = services_sensor

        app_policy_actuator_enabled = (
            self.settings.actuator_app_policy and not self.settings.readonly_mode
        )

        if self.settings.sensors_app_policies or app_policy_actuator_enabled:
            self.app_policy_manager = AppPolicyManager(
                policy_file=self.settings.app_policy_file,
                use_sudo_kill=self.settings.app_policy_use_sudo_kill,
            )
            self.app_policy_manager.load()

            if self.settings.sensors_app_policies:
                self.sensors[AppPoliciesSensor.id] = AppPoliciesSensor(self.app_policy_manager)

            if app_policy_actuator_enabled:
                self.actuators[AppPolicyActuator.id] = AppPolicyActuator(self.app_policy_manager)

        if self.settings.actuator_session and not self.settings.readonly_mode:
            self.actuators[SessionManagerActuator.id] = SessionManagerActuator(
                allowed_users=self.settings.allowed_session_users,
            )

        if self.settings.readonly_mode:
            LOGGER.info("Readonly mode enabled: actuator modules are disabled")

    def _build_virtualbox_sensor(self) -> VirtualBoxSensor | None:
        if not self.settings.virtualbox_user:
            LOGGER.info(
                "Skipping sensor '%s': HA4LINUX_VIRTUALBOX_USER not configured",
                VirtualBoxSensor.id,
            )
            return None

        try:
            return VirtualBoxSensor(user=self.settings.virtualbox_user)
        except ValueError as exc:
            LOGGER.info("Skipping sensor '%s': %s", VirtualBoxSensor.id, exc)
            return None

    def _build_services_sensor(self) -> ServicesSensor | None:
        try:
            return ServicesSensor(watchlist=self.settings.services_watchlist)
        except ValueError as exc:
            LOGGER.info("Skipping sensor '%s': %s", ServicesSensor.id, exc)
            return None

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
