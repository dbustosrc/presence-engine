"""Reusable detection revision event entity."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PresenceEngineConfigEntry
from .entity import PresenceEngineEntity
from .projection import detection_payload


EVENT_TYPES = ["started", "revised", "ended"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PresenceEngineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities((PresenceDetectionEvent(entry.runtime_data),))


class PresenceDetectionEvent(PresenceEngineEntity, EventEntity):
    _attr_translation_key = "detection"
    _attr_event_types = EVENT_TYPES

    def __init__(self, runtime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.entry.entry_id}_detection"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.runtime.async_add_detection_listener(self._async_detection)
        )

    @callback
    def _async_detection(self, detection) -> None:
        if detection.status.startswith("ended"):
            event_type = "ended"
        elif detection.revision == 1:
            event_type = "started"
        else:
            event_type = "revised"
        self._trigger_event(event_type, detection_payload(detection))
        self.async_write_ha_state()
