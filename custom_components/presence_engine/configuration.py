"""Versioned, installation-neutral configuration contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping

from .const import CONFIG_SCHEMA_VERSION, OUTPUT_ENTITY_IDS
from .engine import Quality, TargetKind


ENTITY_ID_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z0-9_]+$")
TOPIC_PATTERN = re.compile(r"^[^\s#+]+(?:/[^\s#+]+)*$")
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class ConfigurationError(ValueError):
    """Raised when an integration configuration violates its contract."""


class AdapterType(str, Enum):
    """Supported source families."""

    FRIGATE_EVENTS = "frigate_events"
    FRIGATE_FACE = "frigate_face"
    PTZ_CONTEXT = "ptz_context"
    BERMUDA_AREA = "bermuda_area"
    MTR_COUNT = "mtr_count"
    COUNT = "count"
    BINARY_PRESENCE = "binary_presence"
    PERSON_HOME = "person_home"
    AUXILIARY_ACTIVITY = "auxiliary_activity"
    SOURCE_HEALTH = "source_health"


class AvailabilityRole(str, Enum):
    """How source availability contributes to coverage health."""

    AUTO = "auto"
    COVERAGE = "coverage"
    OBSERVATION = "observation"


class CameraAdmissionMode(str, Enum):
    """Policy deciding whether a camera event belongs to the presence domain."""

    ANY_DETECTION = "any_detection"
    MAPPED_CURRENT_ZONE = "mapped_current_zone"


@dataclass(frozen=True, slots=True)
class CameraDefinition:
    """Geometry and telemetry inputs for one logical camera."""

    camera_id: str
    floor: str
    admission_mode: CameraAdmissionMode = CameraAdmissionMode.ANY_DETECTION
    fixed_area: str | None = None
    zone_to_area: Mapping[str, str] = field(default_factory=dict)
    profile_to_area: Mapping[str, str] = field(default_factory=dict)
    profile_entity_id: str | None = None
    preset_entity_id: str | None = None
    movement_entity_id: str | None = None
    availability_entity_ids: tuple[str, ...] = ()
    profile_registry_id: str | None = None
    preset_registry_id: str | None = None
    movement_registry_id: str | None = None
    availability_registry_ids: tuple[str, ...] = ()
    availability_unavailable_states: tuple[str, ...] = (
        "unknown",
        "unavailable",
        "none",
        "",
        "off",
        "down",
        "disconnected",
    )
    stable_states: tuple[str, ...] = ("available",)
    moving_states: tuple[str, ...] = ("moving",)

    def __post_init__(self) -> None:
        _require_slug(self.camera_id, "camera_id")
        _require_slug(self.floor, "camera floor")
        if not isinstance(self.admission_mode, CameraAdmissionMode):
            raise ConfigurationError(
                f"camera {self.camera_id} has invalid admission_mode"
            )
        if self.fixed_area is not None:
            _require_slug(self.fixed_area, "camera fixed_area")
        _validate_area_mapping(self.zone_to_area, "zone_to_area")
        _validate_area_mapping(self.profile_to_area, "profile_to_area")
        if (
            self.admission_mode is CameraAdmissionMode.MAPPED_CURRENT_ZONE
            and not self.zone_to_area
        ):
            raise ConfigurationError(
                f"camera {self.camera_id} requires zone_to_area for "
                "mapped_current_zone admission"
            )
        for value in (
            self.profile_entity_id,
            self.preset_entity_id,
            self.movement_entity_id,
        ):
            if value is not None:
                _require_entity_id(value)
        for value in (
            self.profile_registry_id,
            self.preset_registry_id,
            self.movement_registry_id,
        ):
            if value is not None:
                _require_registry_id(value)
        for value in self.availability_entity_ids:
            _require_entity_id(value)
        for value in self.availability_registry_ids:
            _require_registry_id(value)
        if self.availability_registry_ids and (
            len(self.availability_registry_ids) != len(self.availability_entity_ids)
        ):
            raise ConfigurationError(
                f"camera {self.camera_id} must pair each availability registry id "
                "with one entity id"
            )
        if len(set(self.availability_entity_ids)) != len(self.availability_entity_ids):
            raise ConfigurationError(
                f"camera {self.camera_id} contains duplicate availability entities"
            )
        if len(set(self.availability_registry_ids)) != len(
            self.availability_registry_ids
        ):
            raise ConfigurationError(
                f"camera {self.camera_id} contains duplicate availability registry ids"
            )
        if not self.availability_unavailable_states:
            raise ConfigurationError(
                f"camera {self.camera_id} requires availability_unavailable_states"
            )
        if any(not isinstance(state, str) for state in self.availability_unavailable_states):
            raise ConfigurationError(
                f"camera {self.camera_id} availability states must be strings"
            )
        object.__setattr__(self, "zone_to_area", MappingProxyType(dict(self.zone_to_area)))
        object.__setattr__(self, "profile_to_area", MappingProxyType(dict(self.profile_to_area)))
        object.__setattr__(self, "stable_states", tuple(state.casefold() for state in self.stable_states))
        object.__setattr__(self, "moving_states", tuple(state.casefold() for state in self.moving_states))
        object.__setattr__(
            self,
            "availability_entity_ids",
            tuple(self.availability_entity_ids),
        )
        object.__setattr__(
            self,
            "availability_registry_ids",
            tuple(self.availability_registry_ids),
        )
        object.__setattr__(
            self,
            "availability_unavailable_states",
            tuple(state.casefold() for state in self.availability_unavailable_states),
        )

    @property
    def context_entity_ids(self) -> tuple[str, ...]:
        """Return exact HA entities needed for PTZ geometry context."""
        return tuple(
            value
            for value in (
                self.profile_entity_id,
                self.preset_entity_id,
                self.movement_entity_id,
            )
            if value is not None
        )

    @property
    def entity_ids(self) -> tuple[str, ...]:
        """Return every exact HA subscription required by this camera."""
        return tuple(
            dict.fromkeys((*self.context_entity_ids, *self.availability_entity_ids))
        )


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    """One explicitly configured input source."""

    source_id: str
    adapter: AdapterType
    entity_ids: tuple[str, ...] = ()
    entity_registry_ids: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    area: str | None = None
    floor: str | None = None
    identity: str | None = None
    target_kind: TargetKind = TargetKind.UNKNOWN_LIVING
    spatial_quality: Quality = Quality.UNKNOWN
    dependency_group: str | None = None
    coverage_group: str | None = None
    camera_id: str | None = None
    expires_after_seconds: int | None = None
    availability_role: AvailabilityRole = AvailabilityRole.AUTO
    enabled: bool = True
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_slug(self.source_id, "source_id")
        for entity_id in self.entity_ids:
            _require_entity_id(entity_id)
            if entity_id in OUTPUT_ENTITY_IDS:
                raise ConfigurationError(f"source {self.source_id} feeds from an engine output")
        for registry_id in self.entity_registry_ids:
            _require_registry_id(registry_id)
        if self.entity_registry_ids and len(self.entity_registry_ids) != len(self.entity_ids):
            raise ConfigurationError(
                f"source {self.source_id} must pair each registry id with one entity id"
            )
        for topic in self.topics:
            if not TOPIC_PATTERN.fullmatch(topic):
                raise ConfigurationError(f"invalid exact MQTT topic: {topic}")
        for name, value in (
            ("area", self.area),
            ("floor", self.floor),
            ("identity", self.identity),
            ("dependency_group", self.dependency_group),
            ("coverage_group", self.coverage_group),
            ("camera_id", self.camera_id),
        ):
            if value is not None:
                _require_slug(value, name)
        if self.adapter in {AdapterType.FRIGATE_EVENTS, AdapterType.FRIGATE_FACE} and not self.topics:
            raise ConfigurationError(f"source {self.source_id} requires a topic")
        if self.adapter not in {AdapterType.FRIGATE_EVENTS, AdapterType.FRIGATE_FACE} and not self.entity_ids:
            raise ConfigurationError(f"source {self.source_id} requires an entity")
        if self.adapter in {AdapterType.COUNT, AdapterType.BINARY_PRESENCE} and not (
            self.area or self.floor
        ):
            raise ConfigurationError(f"source {self.source_id} requires area or floor")
        if self.adapter is AdapterType.MTR_COUNT:
            total_entity_id = self.options.get("total_entity_id")
            zone_areas = self.options.get("zone_areas")
            if total_entity_id not in self.entity_ids:
                raise ConfigurationError(
                    f"source {self.source_id} requires its total_entity_id in entity_ids"
                )
            if not isinstance(zone_areas, Mapping) or not zone_areas:
                raise ConfigurationError(f"source {self.source_id} requires zone_areas")
            if set(zone_areas) - set(self.entity_ids):
                raise ConfigurationError(
                    f"source {self.source_id} has zone mappings outside entity_ids"
                )
        if self.adapter is AdapterType.PERSON_HOME:
            for option_name in ("ignored_source_ids", "ignored_source_prefixes"):
                values = self.options.get(option_name, ())
                if not isinstance(values, (list, tuple)):
                    raise ConfigurationError(
                        f"source {self.source_id} {option_name} must be a list"
                    )
                for value in values:
                    if not isinstance(value, str):
                        raise ConfigurationError(
                            f"source {self.source_id} {option_name} must contain strings"
                        )
                    _require_entity_id(value)
        if self.adapter is AdapterType.SOURCE_HEALTH:
            if len(self.entity_ids) != 1:
                raise ConfigurationError(
                    f"source {self.source_id} requires exactly one health entity"
                )
            healthy_states = self.options.get("healthy_states")
            unhealthy_states = self.options.get("unhealthy_states")
            if healthy_states is not None and unhealthy_states is not None:
                raise ConfigurationError(
                    f"source {self.source_id} cannot combine healthy_states and "
                    "unhealthy_states"
                )
            for option_name, values in (
                ("healthy_states", healthy_states),
                ("unhealthy_states", unhealthy_states),
            ):
                if values is None:
                    continue
                if not isinstance(values, (list, tuple)) or not values:
                    raise ConfigurationError(
                        f"source {self.source_id} {option_name} must be a non-empty list"
                    )
                if any(not isinstance(value, str) for value in values):
                    raise ConfigurationError(
                        f"source {self.source_id} {option_name} must contain strings"
                    )
        if self.expires_after_seconds is not None and self.expires_after_seconds < 1:
            raise ConfigurationError(
                f"source {self.source_id} expires_after_seconds must be positive"
            )
        object.__setattr__(self, "entity_ids", tuple(dict.fromkeys(self.entity_ids)))
        object.__setattr__(
            self,
            "entity_registry_ids",
            tuple(dict.fromkeys(self.entity_registry_ids)),
        )
        object.__setattr__(self, "topics", tuple(dict.fromkeys(self.topics)))
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))

    @property
    def degrades_coverage_when_unavailable(self) -> bool:
        """Return whether losing this channel reduces observing capability.

        Tracked endpoints describe the thing being observed. Their absence is
        not a failure of the scanners, network or detection infrastructure.
        The explicit role remains available for source families whose local
        semantics differ from the default.
        """
        if self.availability_role is AvailabilityRole.COVERAGE:
            return True
        if self.availability_role is AvailabilityRole.OBSERVATION:
            return False
        return self.adapter not in {
            AdapterType.BERMUDA_AREA,
            AdapterType.PERSON_HOME,
        }


@dataclass(frozen=True, slots=True)
class EngineConfiguration:
    """Complete configuration owned by one config entry."""

    schema_version: int
    areas: Mapping[str, str]
    adjacency: Mapping[str, frozenset[str]]
    identities: Mapping[str, str]
    cameras: Mapping[str, CameraDefinition]
    sources: tuple[SourceDefinition, ...]

    def __post_init__(self) -> None:
        if self.schema_version != CONFIG_SCHEMA_VERSION:
            raise ConfigurationError(
                f"unsupported configuration schema {self.schema_version}; "
                f"expected {CONFIG_SCHEMA_VERSION}"
            )
        for area, floor in self.areas.items():
            _require_slug(area, "area")
            _require_slug(floor, "floor")
        known_areas = set(self.areas)
        for area, neighbours in self.adjacency.items():
            if area not in known_areas:
                raise ConfigurationError(f"adjacency references unknown area: {area}")
            missing = set(neighbours) - known_areas
            if missing:
                raise ConfigurationError(f"adjacency for {area} has unknown areas: {sorted(missing)}")
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ConfigurationError("source_id values must be unique")
        unknown_camera_ids = {
            source.camera_id
            for source in self.sources
            if source.camera_id is not None and source.camera_id not in self.cameras
        }
        if unknown_camera_ids:
            raise ConfigurationError(f"sources reference unknown cameras: {sorted(unknown_camera_ids)}")
        for source in self.sources:
            if source.area is not None and source.area not in known_areas:
                raise ConfigurationError(f"source {source.source_id} references unknown area")
            if source.floor is not None and source.floor not in set(self.areas.values()):
                raise ConfigurationError(f"source {source.source_id} references unknown floor")
            if source.adapter is AdapterType.MTR_COUNT:
                zone_areas = source.options["zone_areas"]
                for area in zone_areas.values():
                    if area is not None and area not in known_areas:
                        raise ConfigurationError(
                            f"source {source.source_id} references unknown MTR zone area"
                        )
        for camera in self.cameras.values():
            referenced_areas = set(camera.zone_to_area.values()) | set(
                camera.profile_to_area.values()
            )
            if camera.fixed_area is not None:
                referenced_areas.add(camera.fixed_area)
            missing = referenced_areas - known_areas
            if missing:
                raise ConfigurationError(
                    f"camera {camera.camera_id} references unknown areas: {sorted(missing)}"
                )
        object.__setattr__(self, "areas", MappingProxyType(dict(self.areas)))
        object.__setattr__(
            self,
            "adjacency",
            MappingProxyType({key: frozenset(value) for key, value in self.adjacency.items()}),
        )
        object.__setattr__(self, "identities", MappingProxyType(dict(self.identities)))
        object.__setattr__(self, "cameras", MappingProxyType(dict(self.cameras)))

    @property
    def entity_ids(self) -> tuple[str, ...]:
        """Return the exact state subscriptions for all enabled sources."""
        values = {
            entity_id
            for source in self.sources
            if source.enabled
            for entity_id in source.entity_ids
        }
        values.update(entity_id for camera in self.cameras.values() for entity_id in camera.entity_ids)
        return tuple(sorted(values))

    @property
    def topics(self) -> tuple[str, ...]:
        """Return exact MQTT subscriptions for all enabled sources."""
        return tuple(
            sorted(
                {
                    topic
                    for source in self.sources
                    if source.enabled
                    for topic in source.topics
                }
            )
        )

    @property
    def identity_ids(self) -> tuple[str, ...]:
        """Return canonical identities that may receive public projections."""
        return tuple(
            sorted(
                {
                    identity
                    for identity in (
                        *self.identities.values(),
                        *(source.identity for source in self.sources),
                    )
                    if identity is not None
                }
            )
        )


def parse_configuration(raw: Mapping[str, Any]) -> EngineConfiguration:
    """Validate JSON-compatible input and return immutable configuration."""
    try:
        cameras = {
            camera_id: CameraDefinition(
                camera_id=camera_id,
                floor=value["floor"],
                admission_mode=CameraAdmissionMode(
                    value.get("admission_mode", CameraAdmissionMode.ANY_DETECTION.value)
                ),
                fixed_area=value.get("fixed_area"),
                zone_to_area=value.get("zone_to_area", {}),
                profile_to_area=value.get("profile_to_area", {}),
                profile_entity_id=value.get("profile_entity_id"),
                preset_entity_id=value.get("preset_entity_id"),
                movement_entity_id=value.get("movement_entity_id"),
                availability_entity_ids=tuple(value.get("availability_entity_ids", ())),
                profile_registry_id=value.get("profile_registry_id"),
                preset_registry_id=value.get("preset_registry_id"),
                movement_registry_id=value.get("movement_registry_id"),
                availability_registry_ids=tuple(
                    value.get("availability_registry_ids", ())
                ),
                availability_unavailable_states=tuple(
                    value.get(
                        "availability_unavailable_states",
                        (
                            "unknown",
                            "unavailable",
                            "none",
                            "",
                            "off",
                            "down",
                            "disconnected",
                        ),
                    )
                ),
                stable_states=tuple(value.get("stable_states", ("available",))),
                moving_states=tuple(value.get("moving_states", ("moving",))),
            )
            for camera_id, value in raw.get("cameras", {}).items()
        }
        sources = tuple(_parse_source(value) for value in raw.get("sources", ()))
        return EngineConfiguration(
            schema_version=int(raw.get("schema_version", 0)),
            areas=dict(raw.get("areas", {})),
            adjacency={
                area: frozenset(neighbours)
                for area, neighbours in raw.get("adjacency", {}).items()
            },
            identities=dict(raw.get("identities", {})),
            cameras=cameras,
            sources=sources,
        )
    except (KeyError, TypeError, ValueError) as err:
        if isinstance(err, ConfigurationError):
            raise
        raise ConfigurationError(f"invalid configuration structure: {err}") from err


def _parse_source(raw: Mapping[str, Any]) -> SourceDefinition:
    return SourceDefinition(
        source_id=str(raw["source_id"]),
        adapter=AdapterType(raw["adapter"]),
        entity_ids=tuple(raw.get("entity_ids", ())),
        entity_registry_ids=tuple(raw.get("entity_registry_ids", ())),
        topics=tuple(raw.get("topics", ())),
        area=raw.get("area"),
        floor=raw.get("floor"),
        identity=raw.get("identity"),
        target_kind=TargetKind(raw.get("target_kind", TargetKind.UNKNOWN_LIVING.value)),
        spatial_quality=Quality(raw.get("spatial_quality", Quality.UNKNOWN.value)),
        dependency_group=raw.get("dependency_group"),
        coverage_group=raw.get("coverage_group"),
        camera_id=raw.get("camera_id"),
        expires_after_seconds=(
            int(raw["expires_after_seconds"])
            if raw.get("expires_after_seconds") is not None
            else None
        ),
        availability_role=AvailabilityRole(
            raw.get("availability_role", AvailabilityRole.AUTO.value)
        ),
        enabled=bool(raw.get("enabled", True)),
        options=dict(raw.get("options", {})),
    )


def _require_entity_id(value: str) -> None:
    if not ENTITY_ID_PATTERN.fullmatch(value):
        raise ConfigurationError(f"invalid entity_id: {value}")


def _require_registry_id(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or any(char.isspace() for char in value):
        raise ConfigurationError(f"invalid entity registry id: {value!r}")


def _require_slug(value: str, name: str) -> None:
    if not isinstance(value, str) or not SLUG_PATTERN.fullmatch(value):
        raise ConfigurationError(f"invalid {name}: {value!r}")


def _validate_area_mapping(value: Mapping[str, str], name: str) -> None:
    for source_name, area in value.items():
        if not isinstance(source_name, str) or not source_name.strip():
            raise ConfigurationError(f"{name} contains an empty key")
        _require_slug(area, f"{name} area")
