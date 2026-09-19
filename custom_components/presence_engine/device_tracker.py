"""Disabled-by-default identity tracker candidates."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PresenceEngineConfigEntry
from .entity import PresenceEngineEntity
from .public_projection import identity_projection


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PresenceEngineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        PresenceIdentityCandidateTracker(runtime, identity)
        for identity in runtime.engine.configuration.identity_ids
    )


class PresenceIdentityCandidateTracker(PresenceEngineEntity, TrackerEntity):
    """Project one canonical identity without writing MQTT or calling services."""

    _attr_source_type = SourceType.BLUETOOTH_LE
    _attr_entity_registry_enabled_default = False

    def __init__(self, runtime, identity: str) -> None:
        super().__init__(runtime)
        self.identity = identity
        self._attr_unique_id = f"{runtime.entry.entry_id}_{identity}_tracker_candidate"
        self._attr_name = f"{identity.replace('_', ' ').title()} tracker candidate"
        self._projection_cache = {}
        self._apply_projection()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._apply_projection()
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self):
        return {
            key: value
            for key, value in self._projection_cache.items()
            if key not in {"state", "entity_picture"}
        }

    @callback
    def _apply_projection(self) -> None:
        self._projection_cache = identity_projection(
            self.coordinator.data,
            self.identity,
            self.runtime.engine.latest_images,
        )
        self._attr_location_name = self._projection_cache["state"]
        self._attr_entity_picture = self._projection_cache["entity_picture"]
