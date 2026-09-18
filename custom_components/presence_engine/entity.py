"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .ha_runtime import HomeAssistantPresenceRuntime, PresenceCoordinator


class PresenceEngineEntity(CoordinatorEntity[PresenceCoordinator]):
    """Entity backed exclusively by the in-memory push coordinator."""

    _attr_has_entity_name = True

    def __init__(self, runtime: HomeAssistantPresenceRuntime) -> None:
        super().__init__(runtime.coordinator)
        self.runtime = runtime
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.entry.entry_id)},
            name="Presence Engine",
            manufacturer="Presence Engine",
            model="Deterministic evidence engine",
            sw_version="0.2.0",
        )
