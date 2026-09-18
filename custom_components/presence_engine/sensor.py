"""Diagnostic projections for comparison and observability."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PresenceEngineConfigEntry
from .const import CONF_COMPARISON_MODE, DEFAULT_COMPARISON_MODE
from .entity import PresenceEngineEntity
from .projection import snapshot_payload


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PresenceEngineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        (
            PresenceSnapshotSensor(runtime),
            PresenceRevisionSensor(runtime),
        )
    )


class PresenceSnapshotSensor(PresenceEngineEntity, SensorEntity):
    _attr_translation_key = "snapshot"
    _attr_icon = "mdi:account-group"

    def __init__(self, runtime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.entry.entry_id}_snapshot"
        self._attr_entity_registry_enabled_default = bool(
            runtime.entry.options.get(CONF_COMPARISON_MODE, DEFAULT_COMPARISON_MODE)
        )

    @property
    def native_value(self):
        snapshot = self.coordinator.data
        if snapshot.count_minimum == snapshot.count_maximum:
            return snapshot.count_minimum
        return f"{snapshot.count_minimum}-{snapshot.count_maximum}"

    @property
    def extra_state_attributes(self):
        return snapshot_payload(self.coordinator.data, self.runtime.engine.latest_images)


class PresenceRevisionSensor(PresenceEngineEntity, SensorEntity):
    _attr_translation_key = "revision"
    _attr_icon = "mdi:source-commit"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.entry.entry_id}_revision"

    @property
    def native_value(self):
        return self.coordinator.data.revision

    @property
    def extra_state_attributes(self):
        return {
            "contract_version": self.coordinator.data.contract_version,
            "evaluated_at": self.coordinator.data.evaluated_at.isoformat(),
            "adapter_failures": [
                {
                    "source_id": failure.source_id,
                    "error_type": failure.error_type,
                    "message": failure.message,
                }
                for failure in self.runtime.engine.failures
            ],
        }
