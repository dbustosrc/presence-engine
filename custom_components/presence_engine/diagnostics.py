"""Diagnostics support without raw payloads, images or credentials."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import PresenceEngineConfigEntry
from .projection import snapshot_payload


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: PresenceEngineConfigEntry,
) -> dict[str, Any]:
    runtime = entry.runtime_data
    configuration = runtime.engine.configuration
    return {
        "configuration": {
            "schema_version": configuration.schema_version,
            "area_count": len(configuration.areas),
            "camera_ids": sorted(configuration.cameras),
            "sources": [
                {
                    "source_id": source.source_id,
                    "adapter": source.adapter.value,
                    "enabled": source.enabled,
                    "entity_count": len(source.entity_ids),
                    "topic_count": len(source.topics),
                }
                for source in configuration.sources
            ],
        },
        "snapshot": snapshot_payload(runtime.engine.snapshot),
        "failures": [
            {
                "source_id": failure.source_id,
                "error_type": failure.error_type,
                "message": failure.message,
            }
            for failure in runtime.engine.failures
        ],
        "discovery": {
            "activated": [
                {
                    "stable_key": candidate.descriptor.stable_key,
                    "entity_id": candidate.descriptor.entity_id,
                    "adapter": candidate.adapter.value,
                }
                for candidate in runtime.activated_discovery
            ],
            "pending": [
                {
                    "stable_key": candidate.descriptor.stable_key,
                    "entity_id": candidate.descriptor.entity_id,
                    "adapter": candidate.adapter.value,
                    "missing_configuration": list(candidate.missing_configuration),
                }
                for candidate in runtime.pending_discovery
            ],
        },
    }
