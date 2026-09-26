"""Presence Engine custom integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeAlias, cast

from .configuration import ConfigurationError, parse_configuration
from .const import (
    CONF_COMPARISON_MODE,
    CONF_CONFIGURATION,
    CONF_MAX_RECORDS,
    CONF_SAVE_DELAY,
    DEFAULT_MAX_RECORDS,
    DEFAULT_SAVE_DELAY,
    DOMAIN,
    PLATFORMS,
    SERVICE_GET_DETECTION,
    SERVICE_GET_SNAPSHOT,
)
from .projection import detection_payload, snapshot_payload

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse

    from .ha_runtime import HomeAssistantPresenceRuntime

    PresenceEngineConfigEntry: TypeAlias = ConfigEntry[HomeAssistantPresenceRuntime]
else:
    PresenceEngineConfigEntry: TypeAlias = Any

async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register read-only query actions once for the integration."""
    import voluptuous as vol

    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import ServiceValidationError
    from homeassistant.helpers import config_validation as cv

    async def async_get_snapshot(call: ServiceCall) -> ServiceResponse:
        runtime = _loaded_runtime(hass, call.data.get("config_entry_id"))
        return snapshot_payload(runtime.engine.snapshot, runtime.engine.latest_images)

    async def async_get_detection(call: ServiceCall) -> ServiceResponse:
        runtime = _loaded_runtime(hass, call.data.get("config_entry_id"))
        detection = runtime.engine.detection(call.data["detection_id"])
        if detection is None:
            raise ServiceValidationError("Detection not found")
        return detection_payload(detection)

    entry_schema = vol.Schema({vol.Optional("config_entry_id"): cv.string})
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SNAPSHOT,
        async_get_snapshot,
        schema=entry_schema,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DETECTION,
        async_get_detection,
        schema=entry_schema.extend({vol.Required("detection_id"): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PresenceEngineConfigEntry,
) -> bool:
    """Set up one validated Presence Engine config entry."""
    from homeassistant.exceptions import ConfigEntryError

    from .ha_runtime import HomeAssistantPresenceRuntime

    try:
        from .discovery import apply_discovery, resolve_raw_registry_bindings
        from .ha_discovery import collect_entity_descriptors
        from .configuration_ui import validate_frigate_settings

        descriptors = collect_entity_descriptors(hass)
        raw_configuration = resolve_raw_registry_bindings(
            entry.data[CONF_CONFIGURATION],
            descriptors,
        )
        configured = parse_configuration(raw_configuration)
        validate_frigate_settings(raw_configuration.get("frigate", {}))
        discovery_plan = apply_discovery(configured, descriptors)
        configuration = discovery_plan.configuration
    except (KeyError, ConfigurationError) as err:
        raise ConfigEntryError(f"Invalid Presence Engine configuration: {err}") from err

    runtime = HomeAssistantPresenceRuntime(
        hass,
        entry,
        configuration,
        activated_discovery=discovery_plan.activated,
        pending_discovery=discovery_plan.pending,
        max_records=int(entry.options.get(CONF_MAX_RECORDS, DEFAULT_MAX_RECORDS)),
        save_delay_seconds=int(entry.options.get(CONF_SAVE_DELAY, DEFAULT_SAVE_DELAY)),
    )
    try:
        await runtime.async_setup()
        entry.runtime_data = runtime
        _migrate_public_projection_registry(hass, entry)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await runtime.async_shutdown()
        raise
    return True


def _migrate_public_projection_registry(
    hass: HomeAssistant,
    entry: PresenceEngineConfigEntry,
) -> None:
    """Promote accepted projections and remove superseded registry entries."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        stable_unique_id = _stable_public_unique_id(
            registry_entry.unique_id,
            entry.entry_id,
        )
        if stable_unique_id is not None:
            registry.async_update_entity(
                registry_entry.entity_id,
                new_unique_id=stable_unique_id,
            )
        elif registry_entry.unique_id.endswith(
            ("_tracker_candidate", "_coverage_candidate")
        ):
            registry.async_remove(registry_entry.entity_id)


def _stable_public_unique_id(unique_id: str, entry_id: str) -> str | None:
    """Return the stable unique ID for an accepted pre-0.4 projection."""
    if unique_id == f"{entry_id}_presence_candidate":
        return f"{entry_id}_presence"
    record_prefix = f"{entry_id}_"
    record_suffix = "_record_candidate"
    if unique_id.startswith(record_prefix) and unique_id.endswith(record_suffix):
        identity = unique_id[len(record_prefix) : -len(record_suffix)]
        if identity:
            return f"{entry_id}_{identity}_record"
    return None


async def async_unload_entry(
    hass: HomeAssistant,
    entry: PresenceEngineConfigEntry,
) -> bool:
    """Unload platforms and every listener owned by the entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_shutdown()
    return True


def _loaded_runtime(
    hass: HomeAssistant,
    requested_entry_id: str | None,
) -> HomeAssistantPresenceRuntime:
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.exceptions import ServiceValidationError

    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
        and (requested_entry_id is None or entry.entry_id == requested_entry_id)
    ]
    if len(entries) != 1:
        raise ServiceValidationError("Exactly one loaded Presence Engine entry is required")
    return cast(PresenceEngineConfigEntry, entries[0]).runtime_data
