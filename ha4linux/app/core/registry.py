import logging
from pathlib import Path
from typing import Any

from app.actuators.app_policy import AppPolicyActuator
from app.actuators.base import Actuator
from app.actuators.message_dispatcher import MessageDispatcherActuator
from app.actuators.session_manager import SessionManagerActuator
from app.actuators.virtualbox_manager import VirtualBoxManagerActuator
from app.core.app_policy_manager import AppPolicyManager
from app.core.config import Settings
from app.core.virtualbox import VirtualBoxClient
from app.sensors.app_policies import AppPoliciesSensor
from app.sensors.base import Sensor
from app.sensors.cpu_load import CpuLoadSensor
from app.sensors.filesystem import FilesystemSensor
from app.sensors.memory import MemorySensor
from app.sensors.network import NetworkSensor
from app.sensors.raid_mdstat import RaidMdstatSensor
from app.sensors.services import ServicesSensor
from app.sensors.system_info import SystemInfoSensor
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
            self.sensors[NetworkSensor.id] = NetworkSensor(
                include_interfaces=self.settings.network_include_interfaces,
                exclude_interfaces=self.settings.network_exclude_interfaces,
                aggregate_mode=self.settings.network_aggregate_mode,
            )

        if self.settings.sensors_raid:
            if Path("/proc/mdstat").exists():
                self.sensors[RaidMdstatSensor.id] = RaidMdstatSensor()
            else:
                LOGGER.info("Skipping sensor '%s': /proc/mdstat not found", RaidMdstatSensor.id)

        virtualbox_actuator_enabled = (
            self.settings.actuator_virtualbox and not self.settings.readonly_mode
        )
        if self.settings.sensors_virtualbox or virtualbox_actuator_enabled:
            virtualbox_client = self._build_virtualbox_client()
            if virtualbox_client is not None:
                if self.settings.sensors_virtualbox:
                    self.sensors[VirtualBoxSensor.id] = VirtualBoxSensor(client=virtualbox_client)
                if virtualbox_actuator_enabled:
                    self.actuators[VirtualBoxManagerActuator.id] = VirtualBoxManagerActuator(
                        client=virtualbox_client,
                        allowed_actions=self.settings.virtualbox_allowed_actions,
                        allowed_vms=self.settings.virtualbox_allowed_vms,
                        start_type=self.settings.virtualbox_start_type,
                        switch_turn_off_action=self.settings.virtualbox_switch_turn_off_action,
                    )

        if self.settings.sensors_services:
            services_sensor = self._build_services_sensor()
            if services_sensor is not None:
                self.sensors[ServicesSensor.id] = services_sensor

        if self.settings.sensors_filesystem:
            self.sensors[FilesystemSensor.id] = FilesystemSensor(
                exclude_types=self.settings.filesystem_exclude_types,
                exclude_mounts=self.settings.filesystem_exclude_mounts,
            )

        if self.settings.sensors_system_info:
            self.sensors[SystemInfoSensor.id] = SystemInfoSensor(
                updates_enabled=self.settings.system_updates_enabled,
                updates_check_interval_sec=self.settings.system_updates_check_interval_sec,
                updates_command_timeout_sec=self.settings.system_updates_command_timeout_sec,
                updates_max_packages=self.settings.system_updates_max_packages,
            )

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

        if self.settings.actuator_message and not self.settings.readonly_mode:
            try:
                message_dispatcher = MessageDispatcherActuator(
                    allowed_targets=self.settings.message_allowed_targets,
                )
            except ValueError as exc:
                LOGGER.info("Skipping actuator '%s': %s", MessageDispatcherActuator.id, exc)
            else:
                if message_dispatcher.available_targets:
                    self.actuators[MessageDispatcherActuator.id] = message_dispatcher
                else:
                    LOGGER.info(
                        "Skipping actuator '%s': no delivery targets available",
                        MessageDispatcherActuator.id,
                    )

        if self.settings.readonly_mode:
            LOGGER.info("Readonly mode enabled: actuator modules are disabled")

    def _build_virtualbox_client(self) -> VirtualBoxClient | None:
        if not self.settings.virtualbox_user:
            LOGGER.info(
                "Skipping virtualbox modules: virtualbox user not configured",
            )
            return None

        try:
            return VirtualBoxClient(
                user=self.settings.virtualbox_user,
                status_cache_ttl_sec=self.settings.virtualbox_status_cache_ttl_sec,
                status_stale_ttl_sec=self.settings.virtualbox_status_stale_ttl_sec,
                failure_backoff_min_sec=self.settings.virtualbox_failure_backoff_min_sec,
                failure_backoff_max_sec=self.settings.virtualbox_failure_backoff_max_sec,
            )
        except ValueError as exc:
            LOGGER.info("Skipping virtualbox modules: %s", exc)
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

    def actuator_capabilities(self) -> dict[str, dict[str, Any]]:
        return {
            actuator_id: actuator.describe()
            for actuator_id, actuator in self.actuators.items()
        }

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
