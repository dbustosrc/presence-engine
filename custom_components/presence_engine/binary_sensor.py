"""Coverage state for Presence Engine."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PresenceEngineConfigEntry
from .entity import PresenceEngineEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PresenceEngineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities((PresenceCoverageSensor(entry.runtime_data),))


class PresenceCoverageSensor(PresenceEngineEntity, BinarySensorEntity):
    _attr_translation_key = "coverage_degraded"
    _attr_icon = "mdi:shield-alert-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.entry.entry_id}_coverage_degraded"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.coverage_degraded

    @property
    def extra_state_attributes(self):
        return {
            "reasons": list(self.coordinator.data.reasons),
            "unavailable_source_ids": list(
                self.coordinator.data.unavailable_source_ids
            ),
            "failures": [failure.source_id for failure in self.runtime.engine.failures],
        }
