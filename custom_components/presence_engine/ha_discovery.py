"""Home Assistant registry bridge for the pure discovery planner."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .discovery import EntityDescriptor


def collect_entity_descriptors(hass: HomeAssistant) -> tuple[EntityDescriptor, ...]:
    """Read registry metadata without scanning state values."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    descriptors: list[EntityDescriptor] = []
    for entry in entity_registry.entities.values():
        device = device_registry.async_get(entry.device_id) if entry.device_id else None
        descriptors.append(
            EntityDescriptor(
                registry_id=entry.id,
                entity_id=entry.entity_id,
                platform=entry.platform,
                unique_id=entry.unique_id,
                domain=entry.domain,
                area_id=entry.area_id or (device.area_id if device else None),
                device_model=device.model if device else None,
                device_class=entry.device_class or entry.original_device_class,
                original_name=entry.original_name,
            )
        )
    return tuple(descriptors)
