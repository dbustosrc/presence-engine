"""Constants for the Presence Engine integration."""

from __future__ import annotations

DOMAIN = "presence_engine"
PLATFORMS = ("sensor", "binary_sensor", "event")
INTEGRATION_VERSION = "0.4.4"

CONF_CONFIGURATION = "configuration"
CONF_COMPARISON_MODE = "comparison_mode"
CONF_MAX_RECORDS = "max_records"
CONF_SAVE_DELAY = "save_delay_seconds"

DEFAULT_COMPARISON_MODE = True
DEFAULT_MAX_RECORDS = 2_000
DEFAULT_SAVE_DELAY = 15

SERVICE_GET_SNAPSHOT = "get_snapshot"
SERVICE_GET_DETECTION = "get_detection"

EVENT_RESULT = f"{DOMAIN}_result"
STORAGE_KEY_PREFIX = DOMAIN
STORAGE_VERSION = 1

CONTRACT_VERSION = 1
CONFIG_SCHEMA_VERSION = 1

FRIGATE_EVENTS_TOPIC = "frigate/events"
FRIGATE_TRACKED_OBJECT_UPDATE_TOPIC = "frigate/tracked_object_update"

OUTPUT_ENTITY_IDS = frozenset(
    {
        "sensor.presence_engine_snapshot",
        "sensor.presence_engine_revision",
        "binary_sensor.presence_engine_coverage_degraded",
        "event.presence_engine_detection",
    }
)
