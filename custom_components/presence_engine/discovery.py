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
    disabled: bool = False
    source_type: str | None = None
    tracking_type: str | None = None
    unit: str | None = None
    receiver_area_id: str | None = None
    ap_attribute: str | None = None

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
    if descriptor.disabled or descriptor.platform == "presence_engine":
        return None
    platform = descriptor.platform.casefold()
    unique_id = descriptor.unique_id.casefold()
    searchable_id = f"{unique_id} {descriptor.entity_id.casefold()}"
    name = (descriptor.original_name or "").casefold()
    model = (descriptor.device_model or "").casefold()

    if descriptor.domain == "device_tracker" and descriptor.source_type == "router" and descriptor.tracking_type != "position":
        return DiscoveryCandidate(descriptor, AdapterType.WIFI_TRACKER, None, ("review",),
            "Network connection and optional AP attachment; not body presence or a person's room.")

    if platform == "bermuda" and descriptor.domain == "sensor" and descriptor.unit in ("m", "cm", "mm"):
        # Bermuda's original entity name and unique-id suffix identify its
        # per-receiver capability, not a user's display name or room guess.
        if (unique_id.endswith("_range") and name.startswith("distance to ")
                or unique_id.endswith("_range_raw") and name.startswith("unfiltered distance to ")):
            return DiscoveryCandidate(descriptor, AdapterType.BERMUDA_SIGNAL, None,
                ("device_id", "receiver_id"), "Receiver distance describes a device; receiver area is optional and must be reviewed.")

    if descriptor.domain == "person":
        return DiscoveryCandidate(
            descriptor,
            AdapterType.PERSON_HOME,
            None,
            ("identity",),
            "person entities prove home scope only; identity mapping must be explicit",
        )

    if platform == "bermuda" and descriptor.domain == "sensor" and (
        name == "area" or name.endswith(" area")
        or not name and (unique_id.endswith("_area") or descriptor.entity_id.casefold().endswith("_area"))
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
        renames = dict(zip(entity_ids, source["entity_ids"], strict=True))
        options = source.get("options", {})
        for field in ("zone_areas", "radar_channels"):
            if isinstance(options.get(field), Mapping):
                options[field] = {renames.get(entity_id, entity_id): value
                                  for entity_id, value in options[field].items()}
        if options.get("total_entity_id") in renames:
            options["total_entity_id"] = renames[options["total_entity_id"]]
    for camera in resolved.get("cameras", {}).values():
        for role in ("profile", "preset", "movement", "telemetry"):
            registry_id = camera.get(f"{role}_registry_id")
            if registry_id in by_registry_id:
                camera[f"{role}_entity_id"] = by_registry_id[registry_id]
        registry_ids = camera.get("availability_registry_ids", ())
        entity_ids = list(camera.get("availability_entity_ids", ()))
        if len(registry_ids) == len(entity_ids):
            camera["availability_entity_ids"] = [
                by_registry_id.get(registry_id, entity_id)
                for registry_id, entity_id in zip(registry_ids, entity_ids, strict=True)
            ]
    return resolved


def apply_discovery(
    configuration: EngineConfiguration,
    descriptors: Iterable[EntityDescriptor],
    *, ignored_registry_ids: Iterable[str] = (), review_registry_ids: Iterable[str] = (),
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
    ignored = set(ignored_registry_ids)
    review_only = set(review_registry_ids)
    activated: list[DiscoveryCandidate] = []
    pending: list[DiscoveryCandidate] = []
    for candidate in discover_candidates(descriptors):
        if candidate.descriptor.registry_id in ignored:
            continue
        if _excluded_endpoint(candidate.descriptor.entity_id, configuration):
            continue
        if candidate.descriptor.entity_id in existing_entities:
            continue
        if candidate.descriptor.device_id in represented_device_ids:
            continue
        normalized = _normalize_candidate(candidate, configuration)
        if candidate.descriptor.registry_id in review_only:
            normalized = replace(normalized, missing_configuration=(*normalized.missing_configuration, "review"))
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


def review_candidates(configuration: EngineConfiguration, descriptors: Iterable[EntityDescriptor]) -> tuple[DiscoveryCandidate, ...]:
    """Offer original compatible channels, not already configured/disabled inputs.

    Unlike legacy automatic radar discovery, manual review may offer a new
    capability on the same device (e.g. receiver distance beside BLE area).
    """
    descriptors = tuple(descriptors)
    represented = {rid for s in configuration.sources for rid in s.entity_registry_ids}
    entities = {eid for s in configuration.sources for eid in s.entity_ids}
    devices = {d.device_id for d in descriptors if d.device_id and (d.registry_id in represented or d.entity_id in entities)}
    camera_entities = {eid for c in configuration.cameras.values() for eid in c.entity_ids}
    return tuple(c for c in discover_candidates(descriptors)
                 if c.descriptor.registry_id not in represented
                 and c.descriptor.entity_id not in entities | camera_entities
                 and not _excluded_endpoint(c.descriptor.entity_id, configuration)
                 and (c.descriptor.device_id not in devices
                      or c.adapter in {AdapterType.WIFI_TRACKER, AdapterType.BERMUDA_AREA, AdapterType.BERMUDA_SIGNAL}))


def _excluded_endpoint(entity_id: str, configuration: EngineConfiguration) -> bool:
    """Honor existing explicit anti-feedback exclusions, not name heuristics."""
    return any(entity_id in s.options.get("ignored_source_ids", ())
               or any(entity_id.startswith(prefix) for prefix in s.options.get("ignored_source_prefixes", ()))
               for s in configuration.sources if s.adapter is AdapterType.PERSON_HOME)


def candidate_source_draft(candidate: DiscoveryCandidate, configuration: EngineConfiguration,
                           descriptors: Iterable[EntityDescriptor]) -> dict:
    """Prefill only verified bindings; ownership and geometry stay reviewable."""
    d = candidate.descriptor
    descriptors = tuple(descriptors)
    draft = {"id": "manual_" + hashlib.sha256(d.registry_id.encode()).hexdigest()[:12],
             "adapter": candidate.adapter.value, "enabled": True,
             "entity_ids": [d.entity_id], "entity_registry_ids": [d.registry_id]}
    options = {}
    if candidate.adapter in {AdapterType.WIFI_TRACKER, AdapterType.BERMUDA_AREA, AdapterType.BERMUDA_SIGNAL}:
        device = "device_" + hashlib.sha256((d.device_id or d.registry_id).encode()).hexdigest()[:12]
        by_entity = {item.entity_id: item for item in descriptors}
        linked = [s for s in configuration.sources if s.adapter in {AdapterType.WIFI_TRACKER, AdapterType.BERMUDA_AREA}
                  and d.device_id and any(by_entity.get(eid) and by_entity[eid].device_id == d.device_id for eid in s.entity_ids)]
        identities = {s.identity for s in linked if s.identity}
        device_ids = {s.options.get("device_id") or s.options.get("target_id") for s in linked} - {None}
        if len(identities) == 1:
            draft["identity"] = identities.pop()
        if configuration.identities.get(d.stable_key):
            draft["identity"] = configuration.identities[d.stable_key]
        if len(device_ids) == 1:
            device = device_ids.pop()
        options["target_id" if candidate.adapter is AdapterType.BERMUDA_AREA else "device_id"] = device
    if candidate.adapter is AdapterType.WIFI_TRACKER:
        draft.update(target_kind="device", spatial_quality="low", availability_role="observation")
        if d.ap_attribute:
            options["ap_attribute"] = d.ap_attribute
    elif candidate.adapter is AdapterType.BERMUDA_SIGNAL:
        raw = d.unique_id.endswith("_range_raw")
        suffix = d.unique_id.removesuffix("_range_raw" if raw else "_range").rsplit("_", 1)[-1]
        options.update(receiver_id="receiver_" + hashlib.sha256(suffix.encode()).hexdigest()[:12],
                       metric="distance_unfiltered" if raw else "distance", history_seconds=120, history_limit=32)
        # Preserve an existing explicit physical receiver binding across phones.
        known_receivers = {s.options["receiver_id"] for s in configuration.sources if s.adapter is AdapterType.BERMUDA_SIGNAL
            for eid in s.entity_ids if by_entity.get(eid) and by_entity[eid].platform == "bermuda"
            and by_entity[eid].unique_id.removesuffix("_range_raw").removesuffix("_range").rsplit("_", 1)[-1] == suffix}
        if len(known_receivers) == 1:
            options["receiver_id"] = known_receivers.pop()
        if d.receiver_area_id in configuration.areas:
            draft["area"] = d.receiver_area_id
            draft["floor"] = configuration.areas[d.receiver_area_id]
        draft.update(target_kind="device", availability_role="observation")
    elif candidate.adapter is not AdapterType.BERMUDA_AREA and candidate.suggested_area in configuration.areas:
        draft["area"] = candidate.suggested_area
        draft["floor"] = configuration.areas[candidate.suggested_area]
    draft["options"] = options
    return draft


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
