"""Lossless draft editing shared by native forms and JSON import."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping
from urllib.parse import urlsplit

from .configuration import ConfigurationError, parse_configuration
from .runtime import PresenceRuntime
from .configuration import SourceDefinition
from datetime import datetime, timezone


EMPTY_CONFIGURATION = {
    "schema_version": 1, "areas": {}, "adjacency": {}, "identities": {},
    "cameras": {}, "sources": [],
}


def validate_draft(raw: Mapping[str, Any]) -> None:
    """Apply the same contract and adapter validation to every input path."""
    PresenceRuntime(parse_configuration(raw), now=lambda: datetime.now(timezone.utc))
    validate_frigate_settings(raw.get("frigate", {}))


def validate_frigate_settings(settings: object) -> None:
    if not isinstance(settings, dict):
        raise ConfigurationError("frigate must be an object")
    for key in ("url", "username", "password", "availability_topic", "cookie_name"):
        if key in settings and not isinstance(settings[key], str):
            raise ConfigurationError(f"Frigate {key} must be text")
    url = settings.get("url", "")
    if url:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ConfigurationError("Frigate URL must be an HTTP(S) base URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError("Frigate URL must not contain credentials, query or fragment")
        if settings.get("username") and parsed.scheme != "https":
            raise ConfigurationError("Frigate credentials require HTTPS")
    if bool(settings.get("username")) != bool(settings.get("password")):
        raise ConfigurationError("Frigate username and password must be supplied together")
    if "discover_faces" in settings and not isinstance(settings["discover_faces"], bool):
        raise ConfigurationError("discover_faces must be boolean")
    topic = settings.get("availability_topic", "frigate/available")
    from .configuration import TOPIC_PATTERN
    if not isinstance(topic, str) or not TOPIC_PATTERN.fullmatch(topic):
        raise ConfigurationError("Frigate availability topic must be exact")


def mapping_rows(values: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{"key": key, "value": value} for key, value in values.items()]


def rows_mapping(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for row in rows:
        key = row["key"].strip()
        if not key or key in result:
            raise ConfigurationError("Mapping keys must be non-empty and unique")
        result[key] = row["value"]
    return result


def patch_item(raw: dict, section: str, key: str, changes: dict) -> dict:
    """Preserve fields the form does not own, including future extensions."""
    draft = deepcopy(raw)
    if section == "sources":
        item = next((item for item in draft[section] if item["source_id"] == key), None)
        if item is None:
            item = {"source_id": key}
            draft[section].append(item)
    else:
        item = draft.setdefault(section, {}).setdefault(key, {})
    item.update(changes)
    return draft


def bind_entities(item: dict, field: str, registry_field: str, entities, descriptors) -> None:
    """Refresh paired stable registry bindings only when selection changes."""
    if item.get(field, []) == entities:
        return
    item[field] = entities
    by_entity = {descriptor.entity_id: descriptor.registry_id for descriptor in descriptors}
    if isinstance(entities, list):
        ids = [by_entity.get(entity) for entity in entities]
        item[registry_field] = ids if all(ids) else []
    elif entities:
        item[registry_field] = by_entity.get(entities)
    else:
        item[registry_field] = None


def delete_item(raw: dict, section: str, key: str) -> dict:
    draft = deepcopy(raw)
    if section == "sources":
        # Exclusion is a retained disabled binding: discovery cannot re-add it.
        for item in draft[section]:
            if item["source_id"] == key:
                item["enabled"] = False
    elif section == "areas":
        draft[section].pop(key, None)
        draft.get("adjacency", {}).pop(key, None)
        for neighbours in draft.get("adjacency", {}).values():
            if key in neighbours:
                neighbours.remove(key)
    else:
        draft[section].pop(key, None)
    validate_draft(draft)
    return draft


def source_to_raw(source: SourceDefinition) -> dict:
    """Materialize a discovered source only when the user edits/excludes it."""
    from dataclasses import fields
    from enum import Enum
    result = {}
    for field in fields(source):
        value = getattr(source, field.name)
        result[field.name] = value.value if isinstance(value, Enum) else dict(value) if isinstance(value, Mapping) else list(value) if isinstance(value, tuple) else value
    return result
