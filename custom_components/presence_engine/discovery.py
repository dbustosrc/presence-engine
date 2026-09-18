"""Conservative source discovery and stable entity-registry reconciliation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import re
from typing import Any, Iterable, Mapping

from .configuration import AdapterType, EngineConfiguration, SourceDefinition
from .engine import Quality, TargetKind


_MTR_ZONE_COUNT = re.compile(r"(?:^|_)zone_[123]_all_target_count(?:$|_)")
_MTR_TOTAL_COUNT = re.compile(r"(?:^|_)(?:all_)?target_count(?:$|_)")
_RADAR_HINTS = ("ld2410", "ld2450", "mmwave", "radar", "presence")


@dataclass(frozen=True, slots=True)
class EntityDescriptor:
    """Installation-neutral entity metadata available from HA registries."""

    registry_id: str
    entity_id: str
    platform: str
    unique_id: str
    domain: str
    area_id: str | None = None
    device_model: str | None = None
    device_class: str | None = None
    original_name: str | None = None
    device_id: str | None = None

    @property
    def stable_key(self) -> str:
        return f"{self.platform}:{self.unique_id}"


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    """A known source family; missing semantics remain explicit."""

    descriptor: EntityDescriptor
    adapter: AdapterType
    suggested_area: str | None
    missing_configuration: tuple[str, ...]
    reason: str

    @property
    def ready(self) -> bool:
        return not self.missing_configuration


@dataclass(frozen=True, slots=True)
class BindingReconciliation:
    """Current entity IDs for configured stable registry entries."""

    resolved: Mapping[str, str]
    renamed: Mapping[str, tuple[str, str]]
    missing_registry_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiscoveryPlan:
    """Effective configuration plus visible accepted and pending candidates."""

    configuration: EngineConfiguration
    activated: tuple[DiscoveryCandidate, ...]
    pending: tuple[DiscoveryCandidate, ...]


def discover_candidate(descriptor: EntityDescriptor) -> DiscoveryCandidate | None:
    """Classify only source families whose semantics are actually known."""
    platform = descriptor.platform.casefold()
    unique_id = descriptor.unique_id.casefold()
    searchable_id = f"{unique_id} {descriptor.entity_id.casefold()}"
    name = (descriptor.original_name or "").casefold()
    model = (descriptor.device_model or "").casefold()

    if descriptor.domain == "person":
        return DiscoveryCandidate(
            descriptor,
            AdapterType.PERSON_HOME,
            None,
            ("identity",),
            "person entities prove home scope only; identity mapping must be explicit",
        )

    if platform == "bermuda" and descriptor.domain == "sensor" and (
        "area" in searchable_id or name.endswith(" area") or name == "area"
    ):
        missing = ["identity"]
        return DiscoveryCandidate(
            descriptor,
            AdapterType.BERMUDA_AREA,
            descriptor.area_id,
            tuple(missing),
            "Bermuda area sensor; owning identity and physical mapping are not inferred",
        )

    if platform == "esphome" and descriptor.domain == "sensor" and (
        "mtr" in model or "mtr" in unique_id
    ):
        if _MTR_ZONE_COUNT.search(searchable_id):
            return DiscoveryCandidate(
                descriptor,
                AdapterType.COUNT,
                None,
                ("physical_area",),
                "MTR zone count requires the measured zone-to-area calibration",
            )
        if _MTR_TOTAL_COUNT.search(searchable_id):
            return DiscoveryCandidate(
                descriptor,
                AdapterType.COUNT,
                None,
                ("coverage_scope",),
                "MTR total count requires an explicit floor or coverage group",
            )

    if platform == "esphome" and descriptor.domain == "binary_sensor" and any(
        hint in unique_id or hint in name for hint in _RADAR_HINTS
    ):
        missing = () if descriptor.area_id else ("physical_area",)
        return DiscoveryCandidate(
            descriptor,
            AdapterType.BINARY_PRESENCE,
            descriptor.area_id,
            missing,
            "ESPHome radar presence; registry area is usable only when configured",
        )

    if platform == "mqtt" and descriptor.domain == "binary_sensor" and (
        "tablet_faces_detected" in unique_id
    ):
        missing = () if descriptor.area_id else ("physical_area",)
        return DiscoveryCandidate(
            descriptor,
            AdapterType.BINARY_PRESENCE,
            descriptor.area_id,
            missing,
            "Known tablet face-presence source",
        )

    return None


def discover_candidates(
    descriptors: Iterable[EntityDescriptor],
) -> tuple[DiscoveryCandidate, ...]:
    """Return deterministic candidates, excluding unknown entity semantics."""
    candidates = (
        candidate
        for descriptor in descriptors
        if (candidate := discover_candidate(descriptor)) is not None
    )
    return tuple(sorted(candidates, key=lambda item: item.descriptor.stable_key))


def reconcile_entity_bindings(
    configured: Mapping[str, str],
    descriptors: Iterable[EntityDescriptor],
) -> BindingReconciliation:
    """Resolve configured registry IDs and identify safe entity-id renames."""
    by_registry_id = {descriptor.registry_id: descriptor for descriptor in descriptors}
    resolved: dict[str, str] = {}
    renamed: dict[str, tuple[str, str]] = {}
    missing: list[str] = []
    for registry_id, configured_entity_id in configured.items():
        descriptor = by_registry_id.get(registry_id)
        if descriptor is None:
            missing.append(registry_id)
            continue
        resolved[registry_id] = descriptor.entity_id
        if descriptor.entity_id != configured_entity_id:
            renamed[registry_id] = (configured_entity_id, descriptor.entity_id)
    return BindingReconciliation(
        resolved=resolved,
        renamed=renamed,
        missing_registry_ids=tuple(sorted(missing)),
    )


def resolve_raw_registry_bindings(
    raw: Mapping[str, Any],
    descriptors: Iterable[EntityDescriptor],
) -> dict[str, Any]:
    """Resolve stable registry IDs while retaining fallback entity IDs in config."""
    resolved = deepcopy(dict(raw))
    by_registry_id = {descriptor.registry_id: descriptor.entity_id for descriptor in descriptors}
    for source in resolved.get("sources", ()):
        registry_ids = source.get("entity_registry_ids", ())
        entity_ids = list(source.get("entity_ids", ()))
        if len(registry_ids) != len(entity_ids):
            continue
        source["entity_ids"] = [
            by_registry_id.get(registry_id, entity_id)
            for registry_id, entity_id in zip(registry_ids, entity_ids, strict=True)
        ]
    for camera in resolved.get("cameras", {}).values():
        for role in ("profile", "preset", "movement"):
            registry_id = camera.get(f"{role}_registry_id")
            if registry_id in by_registry_id:
                camera[f"{role}_entity_id"] = by_registry_id[registry_id]
    return resolved


def apply_discovery(
    configuration: EngineConfiguration,
    descriptors: Iterable[EntityDescriptor],
) -> DiscoveryPlan:
    """Activate unambiguous known sources and expose every other candidate."""
    descriptors = tuple(descriptors)
    existing_entities = {
        entity_id for source in configuration.sources for entity_id in source.entity_ids
    }
    existing_registry_ids = {
        registry_id
        for source in configuration.sources
        for registry_id in source.entity_registry_ids
    }
    represented_device_ids = {
        descriptor.device_id
        for descriptor in descriptors
        if descriptor.device_id is not None
        and (
            descriptor.entity_id in existing_entities
            or descriptor.registry_id in existing_registry_ids
        )
    }
    sources = list(configuration.sources)
    activated: list[DiscoveryCandidate] = []
    pending: list[DiscoveryCandidate] = []
    for candidate in discover_candidates(descriptors):
        if candidate.descriptor.entity_id in existing_entities:
            continue
        if candidate.descriptor.device_id in represented_device_ids:
            continue
        normalized = _normalize_candidate(candidate, configuration)
        source = _candidate_source(normalized, configuration)
        if source is None:
            pending.append(normalized)
            continue
        sources.append(source)
        existing_entities.update(source.entity_ids)
        activated.append(normalized)
    effective = EngineConfiguration(
        schema_version=configuration.schema_version,
        areas=configuration.areas,
        adjacency=configuration.adjacency,
        identities=configuration.identities,
        cameras=configuration.cameras,
        sources=tuple(sources),
    )
    return DiscoveryPlan(effective, tuple(activated), tuple(pending))


def _normalize_candidate(
    candidate: DiscoveryCandidate,
    configuration: EngineConfiguration,
) -> DiscoveryCandidate:
    missing = list(candidate.missing_configuration)
    area = candidate.suggested_area
    identity = configuration.identities.get(candidate.descriptor.stable_key)
    if "identity" in missing and identity:
        missing.remove("identity")
    if area is not None and area not in configuration.areas:
        missing.append("known_physical_area")
    return replace(candidate, missing_configuration=tuple(dict.fromkeys(missing)))


def _candidate_source(
    candidate: DiscoveryCandidate,
    configuration: EngineConfiguration,
) -> SourceDefinition | None:
    if not candidate.ready:
        return None
    descriptor = candidate.descriptor
    digest = hashlib.sha256(descriptor.stable_key.encode()).hexdigest()[:12]
    source_id = f"auto_{digest}"
    identity = configuration.identities.get(descriptor.stable_key)
    target_kind = (
        TargetKind.PERSON
        if candidate.adapter in {AdapterType.PERSON_HOME}
        or "tablet_faces_detected" in descriptor.unique_id.casefold()
        else TargetKind.UNKNOWN_LIVING
    )
    return SourceDefinition(
        source_id=source_id,
        adapter=candidate.adapter,
        entity_ids=(descriptor.entity_id,),
        entity_registry_ids=(descriptor.registry_id,),
        area=candidate.suggested_area,
        identity=identity,
        target_kind=target_kind,
        spatial_quality=Quality.MEDIUM,
        dependency_group=source_id,
        coverage_group=source_id,
        options={"discovered": True, "stable_key": descriptor.stable_key},
    )
