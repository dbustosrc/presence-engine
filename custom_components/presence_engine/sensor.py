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
from .public_projection import identity_projection, public_presence_projection


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
            PresenceCandidateSensor(runtime),
            *(
                PresenceIdentityRecordCandidateSensor(runtime, identity)
                for identity in runtime.engine.configuration.identity_ids
            ),
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


class PresenceCandidateSensor(PresenceEngineEntity, SensorEntity):
    """Disabled-by-default public projection candidate."""

    _attr_name = "Presence candidate"
    _attr_icon = "mdi:radar"
    _attr_entity_registry_enabled_default = False

    def __init__(self, runtime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.entry.entry_id}_presence_candidate"

    @property
    def native_value(self):
        return self._projection["state"]

    @property
    def extra_state_attributes(self):
        return {key: value for key, value in self._projection.items() if key != "state"}

    @property
    def _projection(self):
        return public_presence_projection(
            self.coordinator.data,
            self.runtime.engine.latest_images,
        )


class PresenceIdentityRecordCandidateSensor(PresenceEngineEntity, SensorEntity):
    """Atomic diagnostic record candidate for one configured identity."""

    _attr_icon = "mdi:account-details-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, runtime, identity: str) -> None:
        super().__init__(runtime)
        self.identity = identity
        self._attr_unique_id = f"{runtime.entry.entry_id}_{identity}_record_candidate"
        self._attr_name = f"{identity.replace('_', ' ').title()} record candidate"

    @property
    def native_value(self):
        return self._projection["state"] or "unknown"

    @property
    def entity_picture(self):
        return self._projection["entity_picture"]

    @property
    def extra_state_attributes(self):
        return {
            key: value
            for key, value in self._projection.items()
            if key not in {"state", "entity_picture"}
        }

    @property
    def _projection(self):
        return identity_projection(
            self.coordinator.data,
            self.identity,
            self.runtime.engine.latest_images,
        )
